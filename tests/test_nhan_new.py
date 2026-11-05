"""Kiểm thử nhãn NEW: chỉ gắn cho nội dung đổi so với bản đang hiển thị, từ 04/11/2026.

Chạy: python -m unittest tests.test_nhan_new
"""

import unittest

from crawler import export

RUN_AT = "2026-11-05T13:31:45+07:00"


def muc(id_, noi_dung="a", **them):
    base = {"id": id_, "ten": f"Thủ tục {id_}", "thoi_han": noi_dung, "ngay_cap_nhat": "2026-10-01"}
    base.update(them)
    return base


class NhanNewTest(unittest.TestCase):
    def test_lan_xuat_dau_tien_khong_gan_gi(self):
        items = [muc(1)]
        export._danh_dau_moi(items, None, RUN_AT)
        self.assertIsNone(items[0]["ngay_phat_hien_moi"])

    def test_muc_khong_doi_giu_ngay_cu(self):
        cu = [{**muc(1), "ngay_phat_hien_moi": "2026-11-05"}]
        items = [muc(1)]
        export._danh_dau_moi(items, cu, RUN_AT)
        self.assertEqual(items[0]["ngay_phat_hien_moi"], "2026-11-05")

    def test_muc_doi_noi_dung_duoc_gan_ngay_chay(self):
        cu = [muc(1, "cu")]
        items = [muc(1, "moi")]
        export._danh_dau_moi(items, cu, RUN_AT)
        self.assertEqual(items[0]["ngay_phat_hien_moi"], "2026-11-05")

    def test_muc_moi_duoc_gan_ngay_chay(self):
        cu = [muc(1)]
        items = [muc(1), muc(2)]
        export._danh_dau_moi(items, cu, RUN_AT)
        self.assertIsNone(items[0]["ngay_phat_hien_moi"])
        self.assertEqual(items[1]["ngay_phat_hien_moi"], "2026-11-05")

    def test_truoc_ngay_hieu_luc_khong_gan(self):
        cu = [muc(1, "cu")]
        items = [muc(1, "moi")]
        export._danh_dau_moi(items, cu, "2026-11-03T09:00:00+07:00")
        self.assertIsNone(items[0]["ngay_phat_hien_moi"])

    def test_ngay_cap_nhat_va_kiem_tra_luc_khong_tinh_la_thay_doi(self):
        cu = [{**muc(1), "vbpl": {"kiem_tra_luc": "2026-11-04T01:00:00", "tinh_trang": "x"}}]
        items = [{**muc(1, ngay_cap_nhat="2026-11-05"), "vbpl": {"kiem_tra_luc": "2026-11-05T13:00:00", "tinh_trang": "x"}}]
        export._danh_dau_moi(items, cu, RUN_AT)
        self.assertIsNone(items[0]["ngay_phat_hien_moi"])

    def test_tinh_trang_vbpl_doi_la_thay_doi(self):
        cu = [{**muc(1), "vbpl": {"kiem_tra_luc": "2026-11-04T01:00:00", "tinh_trang": "Còn hiệu lực"}}]
        items = [{**muc(1), "vbpl": {"kiem_tra_luc": "2026-11-05T13:00:00", "tinh_trang": "Hết hiệu lực"}}]
        export._danh_dau_moi(items, cu, RUN_AT)
        self.assertEqual(items[0]["ngay_phat_hien_moi"], "2026-11-05")

    def test_van_ban_ghep_theo_so_ky_hieu(self):
        cu = [{"id": 10, "so_ky_hieu": "1/2026/TT", "trich_yeu": "a"}]
        items = [{"id": 99, "so_ky_hieu": "1/2026/TT", "trich_yeu": "a"}]
        export._danh_dau_moi(items, cu, RUN_AT)
        self.assertIsNone(items[0]["ngay_phat_hien_moi"])


if __name__ == "__main__":
    unittest.main()
