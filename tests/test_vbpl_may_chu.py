"""Kiểm thử đường đẩy một commit và luồng chạy trên server-chat (không gọi mạng, không mở trình duyệt).

Chạy: python -m unittest tests.test_vbpl_may_chu
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from crawler import kham_pha_github, nguon_trang_thai, store, vbpl_may_chu, vbpl_sync


def _tra_loi_cay(cay_cu_entries):
    """Chuỗi phản hồi GitHub giả lập cho các lượt gọi đọc cây."""
    return {"tree": cay_cu_entries, "truncated": False}


class DayNhieuTepTest(unittest.TestCase):
    def test_mot_commit_va_bo_qua_tep_khong_doi(self):
        cu = kham_pha_github.blob_sha(b"giu nguyen")
        cay = [{"path": "a.txt", "type": "blob", "sha": cu}, {"path": "b.txt", "type": "blob", "sha": "x"}]
        tra_loi = [
            (200, {"object": {"sha": "head1"}}),                 # GET ref
            (200, {"tree": {"sha": "cay1"}}),                    # GET commit
            (200, _tra_loi_cay(cay)),                            # GET cây
            (201, {"sha": "blob-b"}),                            # POST blob b.txt
            (201, {"sha": "cay2"}),                              # POST trees
            (201, {"sha": "commit2"}),                           # POST commits
            (200, {}),                                           # PATCH ref
        ]
        with mock.patch.object(kham_pha_github, "_yeu_cau", side_effect=tra_loi) as yc:
            so = kham_pha_github.day_nhieu_tep("tok", {"a.txt": b"giu nguyen", "b.txt": b"moi"}, "thong diep")

        self.assertEqual(so, 1)
        methods = [call.args[0] for call in yc.call_args_list]
        self.assertEqual(methods.count("POST"), 3)  # một blob, một cây, một commit
        self.assertEqual(methods[-1], "PATCH")
        self.assertEqual(yc.call_args_list[-2].args[3]["parents"], ["head1"])

    def test_khong_doi_gi_thi_khong_tao_commit(self):
        cay = [{"path": "a.txt", "type": "blob", "sha": kham_pha_github.blob_sha(b"x")}]
        tra_loi = [(200, {"object": {"sha": "h"}}), (200, {"tree": {"sha": "t"}}), (200, _tra_loi_cay(cay))]
        with mock.patch.object(kham_pha_github, "_yeu_cau", side_effect=tra_loi) as yc:
            so = kham_pha_github.day_nhieu_tep("tok", {"a.txt": b"x"}, "thong diep")

        self.assertEqual(so, 0)
        self.assertEqual(yc.call_count, 3)

    def test_xung_dot_thi_khong_ghi_de(self):
        cay = [{"path": "data/thutuc.db", "type": "blob", "sha": "moi-hon"}]
        tra_loi = [(200, {"object": {"sha": "h"}}), (200, {"tree": {"sha": "t"}}), (200, _tra_loi_cay(cay))]
        with mock.patch.object(kham_pha_github, "_yeu_cau", side_effect=tra_loi):
            with self.assertRaises(kham_pha_github.LoiGitHub):
                kham_pha_github.day_nhieu_tep(
                    "tok", {"data/thutuc.db": b"ban moi"}, "thong diep", sha_cu={"data/thutuc.db": "cu"},
                )


class DauHieuMayChuTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "thutuc.db")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_chua_co_dau_hieu_thi_chua_doc(self):
        from datetime import date
        self.assertFalse(vbpl_sync.may_chu_da_doc(self.conn, date(2026, 11, 13)))

    def test_hom_nay_hoac_hom_qua_thi_da_doc(self):
        from datetime import date
        store.set_state(self.conn, vbpl_sync.MAY_CHU_STATE, "2026-11-13")
        self.assertTrue(vbpl_sync.may_chu_da_doc(self.conn, date(2026, 11, 13)))
        self.assertTrue(vbpl_sync.may_chu_da_doc(self.conn, date(2026, 11, 14)))
        self.assertFalse(vbpl_sync.may_chu_da_doc(self.conn, date(2026, 11, 15)))


class ChayTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.goc = Path(self._tmp.name) / "repo"
        self.goc.mkdir()
        db = Path(self._tmp.name) / "mau.db"
        conn = store.connect(db)
        conn.close()
        self.db_bytes = db.read_bytes()
        self.token = Path(self._tmp.name) / "token.txt"
        self.token.write_text("github_pat_test\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _tai_ve(self, duong_dan):
        if duong_dan == vbpl_may_chu.DB_REL:
            return self.db_bytes
        if duong_dan == vbpl_may_chu.INDEX_REL:
            return b"{}"
        raise AssertionError(duong_dan)

    def _sync_gia(self, conn, run_at, ghi):
        ghi.ghi("vbpl", nguon_trang_thai.OK, "đọc 1 văn bản")
        thu_muc = self.goc / vbpl_may_chu.TEXT_REL
        thu_muc.mkdir(parents=True, exist_ok=True)
        (thu_muc / "van-ban-moi.txt").write_text("toàn văn", encoding="utf-8")

    def test_day_toan_van_moi_va_chi_muc_trong_mot_lan(self):
        captured = {}

        def day_gia(token, tep, thong_diep, sha_cu=None, **kwargs):
            captured.update(tep=tep, thong_diep=thong_diep, sha_cu=sha_cu)
            return len(tep)

        with mock.patch.object(vbpl_may_chu, "tai_ve", side_effect=self._tai_ve), \
                mock.patch.object(vbpl_may_chu.update, "_sync_vbpl", side_effect=self._sync_gia), \
                mock.patch.object(kham_pha_github, "day_nhieu_tep", side_effect=day_gia):
            code = vbpl_may_chu.chay(self.goc, str(self.token))

        self.assertEqual(code, 0)
        self.assertIn("docs/data/vbpl_text/van-ban-moi.txt", captured["tep"])
        self.assertNotIn(vbpl_may_chu.INDEX_REL, captured["tep"])  # chỉ mục không đổi thì không đẩy
        self.assertEqual(set(captured["sha_cu"]), {vbpl_may_chu.DB_REL, vbpl_may_chu.INDEX_REL})

    def test_khong_co_token_thi_khong_day(self):
        with mock.patch.object(vbpl_may_chu, "tai_ve", side_effect=self._tai_ve), \
                mock.patch.object(vbpl_may_chu.update, "_sync_vbpl", side_effect=self._sync_gia), \
                mock.patch.object(kham_pha_github, "day_nhieu_tep") as day:
            code = vbpl_may_chu.chay(self.goc, None)

        self.assertEqual(code, 0)
        day.assert_not_called()

    def test_vbpl_loi_thi_ma_thoat_3(self):
        def sync_loi(conn, run_at, ghi):
            ghi.ghi("vbpl", nguon_trang_thai.BI_CHAN, "HTTP 403")

        with mock.patch.object(vbpl_may_chu, "tai_ve", side_effect=self._tai_ve), \
                mock.patch.object(vbpl_may_chu.update, "_sync_vbpl", side_effect=sync_loi):
            code = vbpl_may_chu.chay(self.goc, None)

        self.assertEqual(code, 3)

    def test_khong_tai_duoc_du_lieu_thi_ma_thoat_2(self):
        def tai_loi(duong_dan):
            raise vbpl_may_chu.LoiTaiVe("mất mạng")

        with mock.patch.object(vbpl_may_chu, "tai_ve", side_effect=tai_loi):
            code = vbpl_may_chu.main(["--goc", str(self.goc)])

        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
