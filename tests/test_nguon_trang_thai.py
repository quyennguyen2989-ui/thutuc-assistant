"""Kiểm thử trạng thái từng nguồn và việc đọc vbpl.vn khi bước tìm văn bản lỗi (không gọi mạng).

Chạy: python -m unittest tests.test_nguon_trang_thai
"""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from crawler import export, nguon_trang_thai, store, vbpl_sync
from crawler.client import BlockedError

CONFIG = {
    "do_tre_giua_cac_yeu_cau_giay": 0,
    "tu_khoa_tim_van_ban_moi": [],
    "chu_ky_tim_van_ban_moi_ngay": 7,
    "tu_ngay_tim_van_ban_moi": "2025-01-01",
}


class TrangThaiNguonTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "thutuc.db")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_loi_nang_hon_ok_trong_cung_lan_chay(self):
        ghi = nguon_trang_thai.Ghi(self.conn, "2026-11-04T08:00:00+07:00")
        ghi.ghi("vbpl", nguon_trang_thai.OK, "đọc 10 văn bản")
        ghi.ghi("vbpl", nguon_trang_thai.LOI, "không tìm được văn bản mới")
        ghi.ghi("vbpl", nguon_trang_thai.OK, "đọc tiếp")
        self.assertEqual(ghi.ket_qua["vbpl"]["trang_thai"], nguon_trang_thai.LOI)
        self.assertIn("không tìm được văn bản mới", ghi.ket_qua["vbpl"]["thong_bao"])
        self.assertIn("đọc tiếp", ghi.ket_qua["vbpl"]["thong_bao"])
        self.assertTrue(ghi.co_loi())

    def test_nguon_ok_khong_bao_loi(self):
        ghi = nguon_trang_thai.Ghi(self.conn, "2026-11-04T08:00:00+07:00")
        ghi.ghi("chinh_phu", nguon_trang_thai.OK, "1 văn bản")
        ghi.ghi("bo_cong_an", nguon_trang_thai.BO_QUA, "bỏ qua")
        self.assertFalse(ghi.co_loi())

    def test_bi_chan_cung_tinh_la_co_loi(self):
        ghi = nguon_trang_thai.Ghi(self.conn, "2026-11-04T08:00:00+07:00")
        ghi.ghi("tphcm", nguon_trang_thai.BI_CHAN, "HTTP 403")
        self.assertTrue(ghi.co_loi())
        self.assertTrue(ghi.co_bi_chan())

    def test_loi_thuong_khong_phai_bi_chan(self):
        ghi = nguon_trang_thai.Ghi(self.conn, "2026-11-04T08:00:00+07:00")
        ghi.ghi("vbpl", nguon_trang_thai.LOI, "timeout")
        self.assertTrue(ghi.co_loi())
        self.assertFalse(ghi.co_bi_chan())

    def test_trang_thai_gan_nhat_va_lan_thanh_cong_gan_nhat(self):
        ghi_1 = nguon_trang_thai.Ghi(self.conn, "2026-11-03T08:00:00+07:00")
        ghi_1.ghi("vbpl", nguon_trang_thai.OK, "ngày 3")
        ghi_2 = nguon_trang_thai.Ghi(self.conn, "2026-11-04T08:00:00+07:00")
        ghi_2.ghi("vbpl", nguon_trang_thai.LOI, "ngày 4 lỗi")

        status = store.load_nguon_status(self.conn)["vbpl"]
        self.assertEqual(status["trang_thai"], nguon_trang_thai.LOI)
        self.assertEqual(status["luc"], "2026-11-04T08:00:00+07:00")
        self.assertEqual(status["thanh_cong_gan_nhat"], "2026-11-03T08:00:00+07:00")

    def test_xuat_meta_co_ten_nguon(self):
        ghi = nguon_trang_thai.Ghi(self.conn, "2026-11-04T08:00:00+07:00")
        ghi.ghi("cong_dvc_quoc_gia", nguon_trang_thai.OK, "146 thủ tục")
        meta = export._trang_thai_nguon(self.conn)
        self.assertEqual(meta["cong_dvc_quoc_gia"]["ten"], nguon_trang_thai.ten("cong_dvc_quoc_gia"))
        self.assertEqual(meta["cong_dvc_quoc_gia"]["trang_thai"], "ok")
        self.assertEqual(meta["cong_dvc_quoc_gia"]["thanh_cong_gan_nhat"], "2026-11-04T08:00:00+07:00")

    def test_loi_tim_van_ban_khong_chan_viec_doc_trang_thai(self):
        store.upsert_vbpl(self.conn, {"url": "https://vbpl.vn/a", "so_ky_hieu": "1/2025/TT-BCA"})
        self.conn.commit()

        def fake_read(urls, on_result, **kwargs):
            for url in urls:
                on_result(url, {"tieu_de": "Thông tư 1", "tinh_trang": "Còn hiệu lực",
                                "ngay_hieu_luc": "01/01/2025", "ngay_cap_nhat": "02/01/2026"})

        with mock.patch("crawler.vbpl_sync.discover", side_effect=RuntimeError("sitemap lỗi")), \
                mock.patch("crawler.vbpl.read_detail_pages", side_effect=fake_read):
            so_doc, so_loi, loi_tim, so_khong_con = vbpl_sync.sync(
                self.conn, ["1/2025/TT-BCA"], "2026-11-04T08:00:00+07:00", date(2026, 11, 4), CONFIG,
            )

        self.assertEqual((so_doc, so_loi, loi_tim, so_khong_con), (1, 0, "sitemap lỗi", 0))
        row = store.load_vbpl(self.conn)[0]
        self.assertEqual(row["tinh_trang"], "Còn hiệu lực")
        self.assertIsNone(store.get_state(self.conn, vbpl_sync.SEARCHED_STATE))

    def test_bi_chan_khi_tim_van_ban_van_doc_trang_thai(self):
        store.upsert_vbpl(self.conn, {"url": "https://vbpl.vn/a", "so_ky_hieu": "1/2025/TT-BCA"})
        self.conn.commit()

        def fake_read(urls, on_result, **kwargs):
            for url in urls:
                on_result(url, {"tieu_de": "Thông tư 1", "tinh_trang": "Còn hiệu lực",
                                "ngay_hieu_luc": "01/01/2025", "ngay_cap_nhat": "02/01/2026"})

        with mock.patch("crawler.vbpl_sync.discover", side_effect=BlockedError("HTTP 403")),                 mock.patch("crawler.vbpl.read_detail_pages", side_effect=fake_read):
            so_doc, so_loi, loi_tim, so_khong_con = vbpl_sync.sync(
                self.conn, ["1/2025/TT-BCA"], "2026-11-04T08:00:00+07:00", date(2026, 11, 4), CONFIG,
            )
        self.assertIn("bị chặn", loi_tim)
        self.assertEqual((so_doc, so_loi), (1, 0))
        self.assertEqual(store.load_vbpl(self.conn)[0]["tinh_trang"], "Còn hiệu lực")


if __name__ == "__main__":
    unittest.main()
