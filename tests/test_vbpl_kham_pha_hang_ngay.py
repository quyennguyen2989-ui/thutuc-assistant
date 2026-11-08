"""Kiểm thử lịch đồng bộ vbpl.vn: phát hiện văn bản mới mỗi ngày, đọc ngay văn bản mới,
đọc lại toàn bộ tình trạng mỗi 7 ngày (không gọi mạng thật).

Chạy: python -m unittest tests.test_vbpl_kham_pha_hang_ngay
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from crawler import store, vbpl_sync

CONFIG = {
    "do_tre_giua_cac_yeu_cau_giay": 0,
    "tu_khoa_tim_van_ban_moi": [],
    "chu_ky_tim_van_ban_moi_ngay": 1,
    "chu_ky_doc_day_du_ngay": 7,
    "tu_ngay_tim_van_ban_moi": "2025-01-01",
}
MOI = "https://vbpl.vn/van-ban/chi-tiet/van-ban-moi--33333"
CU = "https://vbpl.vn/van-ban/chi-tiet/van-ban-cu--44444"


class LichDongBoTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "test.db")
        store.upsert_vbpl(self.conn, {"url": CU, "so_ky_hieu": "1/2025/TT-BCA", "kiem_tra_luc": "2026-11-01T08:00:00+07:00"})
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def _chay(self, ngay):
        captured = {}

        def fake_read(conn, run_at, delay, keywords, only_urls=None):
            captured["only_urls"] = only_urls
            return (0, 0, 0)

        summary = {"so_sanh_duoc": 1, "theo_so_ky_hieu": 0, "van_ban_moi": 1, "url_moi": [MOI]}
        with mock.patch("crawler.vbpl_sync.discover", return_value=summary), \
                mock.patch("crawler.vbpl_sync.read_statuses", side_effect=fake_read), \
                mock.patch("crawler.vbpl_sync.watched_numbers", return_value=[]):
            vbpl_sync.sync(self.conn, [], "2026-11-08T08:00:00+07:00", ngay, CONFIG)
        self.conn.commit()
        return captured["only_urls"]

    def test_lan_dau_doc_day_du_va_ghi_nho_ngay(self):
        only = self._chay(date(2026, 11, 8))
        self.assertIsNone(only)
        self.assertEqual(store.get_state(self.conn, vbpl_sync.DOC_DAY_DU_STATE), "2026-11-08")

    def test_ngay_thuong_chi_doc_van_ban_moi_va_van_can_doc(self):
        store.set_state(self.conn, vbpl_sync.DOC_DAY_DU_STATE, "2026-11-07")
        only = self._chay(date(2026, 11, 8))
        self.assertIsNotNone(only)
        self.assertIn(MOI, only)
        self.assertNotIn(CU, only)  # đã kiểm tra gần đây, không lỗi, không có ngày sửa mới
        self.assertEqual(store.get_state(self.conn, vbpl_sync.DOC_DAY_DU_STATE), "2026-11-07")

    def test_du_7_ngay_thi_doc_day_du_lai(self):
        store.set_state(self.conn, vbpl_sync.DOC_DAY_DU_STATE, "2026-11-01")
        self.assertIsNone(self._chay(date(2026, 11, 8)))
        self.assertEqual(store.get_state(self.conn, vbpl_sync.DOC_DAY_DU_STATE), "2026-11-08")


if __name__ == "__main__":
    unittest.main()
