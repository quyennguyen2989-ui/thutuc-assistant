"""Lỗi của Cổng Dịch vụ công Quốc gia chỉ ghi nhận, không làm lần chạy báo lỗi (không gọi mạng).

Chạy: python -m unittest tests.test_loi_dvc_khong_bao_do
"""

import tempfile
import unittest
from pathlib import Path

from crawler import nguon_trang_thai, store


class LoiDvcTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "test.db")
        self.ghi = nguon_trang_thai.Ghi(self.conn, "2026-11-10T09:00:00+07:00")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_chi_dvc_loi_thi_khong_tinh_la_loi_lan_chay(self):
        self.ghi.ghi("vbpl", nguon_trang_thai.OK, "ok")
        self.ghi.ghi("cong_dvc_quoc_gia", nguon_trang_thai.LOI, "quá giờ")
        self.assertFalse(self.ghi.co_loi(bo_qua=frozenset({"cong_dvc_quoc_gia"})))
        self.assertTrue(self.ghi.co_loi())

    def test_nguon_khac_loi_van_bao_loi(self):
        self.ghi.ghi("cong_dvc_quoc_gia", nguon_trang_thai.LOI, "quá giờ")
        self.ghi.ghi("tphcm", nguon_trang_thai.LOI, "quá giờ")
        self.assertTrue(self.ghi.co_loi(bo_qua=frozenset({"cong_dvc_quoc_gia"})))

    def test_dvc_bi_chan_van_bao_loi(self):
        self.ghi.ghi("cong_dvc_quoc_gia", nguon_trang_thai.BI_CHAN, "HTTP 403")
        self.assertTrue(self.ghi.co_bi_chan())
        self.assertTrue(self.ghi.co_loi(bo_qua=frozenset({"cong_dvc_quoc_gia"})))


if __name__ == "__main__":
    unittest.main()
