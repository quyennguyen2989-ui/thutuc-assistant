"""Kiểm thử logic chuẩn hóa và phát hiện thay đổi (không gọi mạng).

Chạy: python -m unittest discover -s tests
"""

import tempfile
import unittest
from pathlib import Path

from crawler import normalize, store, update


def van_ban(record_id, **overrides):
    record = {
        "id": record_id,
        "so_ky_hieu": f"{record_id}/2019/TT-BCA",
        "loai": "Thông tư",
        "linh_vuc": "Cấp CCCD",
        "co_quan_ban_hanh": "Bộ công an",
        "nguoi_ky": "",
        "trich_yeu": "Trích yếu",
        "ngay_ban_hanh": "2019-10-01",
        "ngay_hieu_luc": "2019-11-18",
        "hieu_luc_theo_cong": True,
        "file_dinh_kem": "",
    }
    record.update(overrides)
    return record


class NormalizeTest(unittest.TestCase):
    def test_tthc_strips_plus_prefix_and_drops_ids(self):
        detail = {
            "TTHC": {"TEN_THU_TUC": "Thủ tục A", "HIEU_LUC": 1},
            "CCPL": [{"ID": 1, "ID_TTHC": 9, "VAN_BAN": "+ Luật 97/2015/QH13: Luật phí"}],
            "YEUCAU": [{"ID": 5, "ID_TTHC": 9, "NOI_DUNG": "Có CMND"}],
            "MAUDON": [],
            "LEPHI": [{"ID": 7, "MUC_PHI": "Miễn phí", "TEN_PHI": "", "VAN_BAN": ""}],
        }
        record = normalize.normalize_tthc({"ID": 9}, detail)

        self.assertEqual(record["can_cu"], ["Luật 97/2015/QH13: Luật phí"])
        self.assertEqual(record["yeu_cau"], [{"NOI_DUNG": "Có CMND"}])
        self.assertEqual(record["le_phi"][0]["muc"], "Miễn phí")
        self.assertTrue(record["hieu_luc_theo_cong"])

    def test_van_ban_flag_is_read_from_string_one(self):
        record = normalize.normalize_van_ban(
            {"ID": 1, "SO_KY_HIEU": "1/2019/TT", "HIEU_LUC": "1"}
        )
        self.assertTrue(record["hieu_luc_theo_cong"])


class ChangeDetectionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def _sync(self, records, run_at, first_run=False):
        with self.conn:
            count = store.sync_records(self.conn, "van_ban", records, run_at, first_run)
            store.log_run(self.conn, run_at, "ok", len(records), 0, count)
        return count

    def _changes(self):
        return store.load_changes(self.conn)

    def test_first_run_records_baseline_without_changes(self):
        count = self._sync([van_ban(1), van_ban(2)], "2026-11-01T08:00:00", first_run=True)
        self.assertEqual(count, 0)
        self.assertEqual(self._changes(), [])

    def test_unchanged_run_produces_no_changes(self):
        self._sync([van_ban(1)], "2026-11-01T08:00:00", first_run=True)
        count = self._sync([van_ban(1)], "2026-11-02T08:00:00")
        self.assertEqual(count, 0)

    def test_changed_field_is_logged_with_diff(self):
        self._sync([van_ban(1)], "2026-11-01T08:00:00", first_run=True)
        count = self._sync([van_ban(1, ngay_hieu_luc="2020-01-01")], "2026-11-02T08:00:00")

        self.assertEqual(count, 1)
        change = self._changes()[0]
        self.assertEqual(change["change_type"], "thay_doi")
        self.assertEqual(change["diff"]["ngay_hieu_luc"], {"cu": "2019-11-18", "moi": "2020-01-01"})

    def test_new_record_is_logged_after_baseline(self):
        self._sync([van_ban(1)], "2026-11-01T08:00:00", first_run=True)
        count = self._sync([van_ban(1), van_ban(2)], "2026-11-02T08:00:00")

        self.assertEqual(count, 1)
        self.assertEqual(self._changes()[0]["change_type"], "moi")

    def test_disappearing_record_is_marked_not_deleted(self):
        self._sync([van_ban(1), van_ban(2)], "2026-11-01T08:00:00", first_run=True)
        self._sync([van_ban(1)], "2026-11-02T08:00:00")

        self.assertEqual(self._changes()[0]["change_type"], "khong_con_tren_cong")
        loaded = {record["id"]: record for record in store.load_records(self.conn, "van_ban")}
        self.assertTrue(loaded[2]["_missing"])
        self.assertFalse(loaded[1]["_missing"])

    def test_returning_record_is_logged_as_back(self):
        self._sync([van_ban(1), van_ban(2)], "2026-11-01T08:00:00", first_run=True)
        self._sync([van_ban(1)], "2026-11-02T08:00:00")
        self._sync([van_ban(1), van_ban(2)], "2026-11-03T08:00:00")

        self.assertEqual(self._changes()[0]["change_type"], "quay_lai")


class SanityCheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "test.db")
        with self.conn:
            store.sync_records(
                self.conn, "van_ban", [van_ban(i) for i in range(1, 11)], "2026-11-01T08:00:00", True
            )

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_zero_records_is_rejected(self):
        with self.assertRaises(RuntimeError):
            update._check_sanity(self.conn, "van_ban", 0)

    def test_large_drop_is_rejected(self):
        with self.assertRaises(RuntimeError):
            update._check_sanity(self.conn, "van_ban", 4)

    def test_normal_count_is_accepted(self):
        update._check_sanity(self.conn, "van_ban", 9)


if __name__ == "__main__":
    unittest.main()
