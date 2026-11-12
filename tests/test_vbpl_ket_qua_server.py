"""Kiểm thử cách CI nạp kết quả tìm văn bản do server-chat gửi (không gọi mạng).

Chạy: python -m unittest tests.test_vbpl_ket_qua_server
"""

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from crawler import store, vbpl_sync


def _ghi_ket_qua(path, tao_luc, van_ban):
    path.write_text(json.dumps({"tao_luc": tao_luc, "van_ban": van_ban}, ensure_ascii=False), encoding="utf-8")


class DocKetQuaServerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "vbpl_kham_pha.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_thieu_tep_thi_none(self):
        self.assertIsNone(vbpl_sync.doc_ket_qua_server(date(2026, 11, 12), self.path))

    def test_ket_qua_hom_nay_duoc_nhan(self):
        _ghi_ket_qua(self.path, "2026-11-12T07:00:00+07:00", [{"url": "https://vbpl.vn/a"}])
        self.assertEqual(vbpl_sync.doc_ket_qua_server(date(2026, 11, 12), self.path), [{"url": "https://vbpl.vn/a"}])

    def test_ket_qua_hom_qua_duoc_nhan_nhung_cu_hon_thi_bo(self):
        _ghi_ket_qua(self.path, "2026-11-11T07:00:00+07:00", [])
        self.assertEqual(vbpl_sync.doc_ket_qua_server(date(2026, 11, 12), self.path), [])
        self.assertIsNone(vbpl_sync.doc_ket_qua_server(date(2026, 11, 13), self.path))

    def test_ket_qua_moi_hon_ngay_chay_thi_bo(self):
        _ghi_ket_qua(self.path, "2026-11-12T07:00:00+07:00", [])
        self.assertIsNone(vbpl_sync.doc_ket_qua_server(date(2026, 11, 4), self.path))


class NapKetQuaServerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "thutuc.db")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_van_ban_moi_duoc_ghi_va_tra_ve_de_doc(self):
        van_ban = [{"url": "https://vbpl.vn/a", "so_ky_hieu": "01/2026/TT-BCA", "sheet": 1, "lastmod": "2026-01-05"},
                   {"url": "https://vbpl.vn/b", "sheet": 20, "lastmod": "2026-02-01"}]
        url_moi = vbpl_sync.nap_ket_qua_server(self.conn, van_ban, date(2026, 11, 12))

        self.assertEqual(url_moi, {"https://vbpl.vn/a", "https://vbpl.vn/b"})
        rows = {row["url"]: row for row in store.load_vbpl(self.conn)}
        self.assertEqual(rows["https://vbpl.vn/a"]["so_ky_hieu"], "01/2026/TT-BCA")
        self.assertIsNone(rows["https://vbpl.vn/b"]["so_ky_hieu"])
        self.assertEqual(store.get_state(self.conn, vbpl_sync.DISCOVERY_STATE), "2026-11-12")

    def test_van_ban_da_co_khong_bi_doc_lai_va_giu_so_ky_hieu(self):
        store.upsert_vbpl(self.conn, {"url": "https://vbpl.vn/a", "so_ky_hieu": "01/2026/TT-BCA"})
        self.conn.commit()

        url_moi = vbpl_sync.nap_ket_qua_server(
            self.conn, [{"url": "https://vbpl.vn/a", "sheet": 1, "lastmod": "2026-01-05"}], date(2026, 11, 12),
        )

        self.assertEqual(url_moi, set())
        row = store.load_vbpl(self.conn)[0]
        self.assertEqual(row["so_ky_hieu"], "01/2026/TT-BCA")
        self.assertEqual(row["lastmod"], "2026-01-05")


if __name__ == "__main__":
    unittest.main()
