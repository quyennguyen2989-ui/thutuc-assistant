"""Kiểm thử quy tắc phạm vi lịch sử: bỏ văn bản đã hết hiệu lực từ 2025 trở về trước, trừ căn cứ của thủ tục."""

import unittest

from crawler import export, nguon_chinh_thuc as nguon

TU_KHOA = nguon.tu_khoa_giai_doan(2)


class PhamViTest(unittest.TestCase):
    def test_thu_tuc_cua_nganh_khac_bi_bo(self):
        row = {"so_ky_hieu": "1234/QĐ-UBND", "trich_yeu": "Công bố thủ tục hành chính lĩnh vực hải quan",
               "tinh_trang": "Còn hiệu lực", "ngay_hieu_luc": "2026-01-01"}
        self.assertFalse(export._trong_pham_vi(row, set(), TU_KHOA))

    def test_thu_tuc_cua_cong_an_duoc_giu(self):
        row = {"so_ky_hieu": "60/2026/TT-BCA", "trich_yeu": "Quy định thủ tục hành chính",
               "tinh_trang": "Còn hiệu lực", "ngay_hieu_luc": "2026-12-01"}
        self.assertTrue(export._trong_pham_vi(row, set(), TU_KHOA))

    def test_thu_tuc_co_linh_vuc_cu_the_duoc_giu(self):
        row = {"so_ky_hieu": "5/2026/TT-XYZ", "trich_yeu": "Quy định thủ tục đăng ký cư trú",
               "tinh_trang": "Còn hiệu lực", "ngay_hieu_luc": "2026-01-01"}
        self.assertTrue(export._trong_pham_vi(row, set(), TU_KHOA))

    def test_thu_tuc_nganh_khac_van_la_can_cu_thi_duoc_giu(self):
        row = {"so_ky_hieu": "1234/QĐ-UBND", "trich_yeu": "Công bố thủ tục hành chính lĩnh vực hải quan",
               "tinh_trang": "Hết hiệu lực", "ngay_hieu_luc": "2010-01-01"}
        self.assertTrue(export._trong_pham_vi(row, {"1234/QĐ-UBND"}, TU_KHOA))

    def test_phu_hop_pham_vi_theo_nguon_nguoi_ban_hanh(self):
        ten = "Quyết định công bố thủ tục hành chính lĩnh vực đăng ký xe"
        self.assertFalse(nguon.phu_hop_pham_vi(ten, nguon.GIAI_DOAN_1, "12/QĐ-UBND"))
        self.assertTrue(nguon.phu_hop_pham_vi(ten, nguon.GIAI_DOAN_1, "12/2026/TT-BCA"))
        self.assertTrue(nguon.phu_hop_pham_vi("Thông tư quy định thủ tục hành chính", nguon.GIAI_DOAN_1,
                                              "12/2026/TT-BCA"))
        self.assertTrue(nguon.phu_hop_pham_vi("Quyết định thủ tục hành chính của Công an thành phố",
                                              nguon.GIAI_DOAN_1, "", "Công an thành phố"))

    def test_van_ban_giu_theo_so_duoc_giu_du_ten_khong_co_cong_an(self):
        ten = "Nghị định quy định hình thức xử phạt trục xuất, tạm giữ người theo thủ tục hành chính"
        self.assertTrue(nguon.phu_hop_pham_vi(ten, nguon.GIAI_DOAN_1, "59/2026/NĐ-CP"))
        self.assertTrue(nguon.phu_hop_pham_vi(ten, nguon.GIAI_DOAN_1, "59/2026/ND-CP"))
        self.assertFalse(nguon.phu_hop_pham_vi(ten, nguon.GIAI_DOAN_1, "60/2026/NĐ-CP"))

    def test_phu_hop_pham_vi_giu_linh_vuc_cu_the(self):
        self.assertTrue(nguon.phu_hop_pham_vi("Thông tư quy định về thủ tục cấp thẻ Căn cước", nguon.GIAI_DOAN_1))
        self.assertFalse(nguon.phu_hop_pham_vi("Quy định về kinh doanh vàng", nguon.GIAI_DOAN_1))

    def test_giai_doan_3_them_dang_ky_cong_an(self):
        tu_khoa = nguon.tu_khoa_giai_doan(3)
        self.assertIn("moi-sinh", tu_khoa)
        self.assertIn("thuong-tru", tu_khoa)
        self.assertTrue(nguon.phu_hop_pham_vi("Thông tư quy định đăng ký thường trú cho trẻ mới sinh",
                                              tu_khoa, "12/2026/TT-BCA"))
        self.assertFalse(nguon.phu_hop_pham_vi("Nghị định quy định đăng ký khai sinh cho trẻ mới sinh",
                                               tu_khoa, "12/2026/NĐ-CP"))
        self.assertTrue(nguon.phu_hop_pham_vi("Nghị định quy định đăng ký khai sinh cho trẻ mới sinh",
                                              tu_khoa, "12/2026/TT-BCA"))

    def test_dang_ky_xe_can_co_dau_hieu_cong_an(self):
        tu_khoa = nguon.tu_khoa_giai_doan(3)
        ten = "Thông tư quy định đăng ký xe máy"
        self.assertFalse(nguon.phu_hop_pham_vi(ten, tu_khoa, "05/2024/TT-BGTVT"))
        self.assertTrue(nguon.phu_hop_pham_vi(ten, tu_khoa, "58/2020/TT-BCA"))

    def test_phong_chay_la_linh_vuc_cu_the(self):
        tu_khoa = nguon.tu_khoa_giai_doan(3)
        self.assertTrue(nguon.phu_hop_pham_vi("Nghị định quy định về phòng cháy và chữa cháy", tu_khoa, "136/2020/NĐ-CP"))

    def test_van_ban_bi_khop_nham_bi_loai(self):
        tu_khoa = nguon.tu_khoa_giai_doan(3)
        ten = "sửa đổi, bổ sung một số điều của Nghị định số 105/2025/NĐ-CP về phòng cháy, chữa cháy"
        self.assertFalse(nguon.phu_hop_pham_vi(ten, tu_khoa, "347/2026/NĐ-CP"))
        self.assertTrue(nguon.phu_hop_pham_vi(ten, tu_khoa, "301/2026/NĐ-CP"))

    def test_toan_van_chi_luu_van_ban_trong_pham_vi(self):
        from crawler import vbpl_text

        tu_khoa = nguon.tu_khoa_giai_doan(3)
        xe_bgtvt = {"tinh_trang": "Còn hiệu lực", "so_ky_hieu": "05/2024/TT-BGTVT",
                    "tieu_de": "Thông tư quy định đăng ký xe", "url": "u1", "sheet": ""}
        xe_bca = dict(xe_bgtvt, so_ky_hieu="58/2020/TT-BCA")
        self.assertFalse(vbpl_text._wanted(xe_bgtvt, [], tu_khoa))
        self.assertTrue(vbpl_text._wanted(xe_bca, [], tu_khoa))

    def test_loc_pham_vi_bo_dong_khong_co_tu_khoa(self):
        rows = [{"so_ky_hieu": "76/2018/NĐ-CP", "trich_yeu": "ngày 15 tháng 5 năm 2018 của Chính phủ quy định "
                 "chi tiết Luật Chuyển giao công nghệ", "co_quan_ban_hanh": ""}]
        self.assertEqual(nguon.loc_pham_vi(rows, TU_KHOA), [])

    def test_loc_pham_vi_bo_thu_tuc_nganh_khac_da_luu(self):
        rows = [
            {"so_ky_hieu": "1234/QĐ-UBND", "trich_yeu": "Công bố thủ tục hành chính lĩnh vực thủy sản",
             "co_quan_ban_hanh": ""},
            {"so_ky_hieu": "60/2026/TT-BCA", "trich_yeu": "Quy định thủ tục hành chính", "co_quan_ban_hanh": ""},
        ]
        kept = nguon.loc_pham_vi(rows, TU_KHOA)
        self.assertEqual([row["so_ky_hieu"] for row in kept], ["60/2026/TT-BCA"])

    def test_van_ban_tu_2025_tro_di_duoc_lay(self):
        self.assertTrue(export._trong_pham_vi({"so_ky_hieu": "362/2025/NĐ-CP", "tinh_trang": "Hết hiệu lực"}, set()))

    def test_van_ban_cu_het_hieu_luc_bi_bo(self):
        row = {"so_ky_hieu": "09/2006/CT-UBND", "tinh_trang": "Hết hiệu lực", "ngay_hieu_luc": "2006-03-30"}
        self.assertFalse(export._trong_pham_vi(row, set()))

    def test_van_ban_cu_van_con_hieu_luc_duoc_giu(self):
        row = {"so_ky_hieu": "331/2016/TT-BTC", "tinh_trang": "Còn hiệu lực", "ngay_hieu_luc": "2017-01-01"}
        self.assertTrue(export._trong_pham_vi(row, set()))

    def test_van_ban_cu_het_hieu_luc_mot_phan_duoc_giu(self):
        row = {"so_ky_hieu": "02/2014/TT-BCA", "tinh_trang": "Hết hiệu lực một phần", "ngay_hieu_luc": "2014-02-01"}
        self.assertTrue(export._trong_pham_vi(row, set()))

    def test_can_cu_cua_thu_tuc_luon_duoc_giu(self):
        row = {"so_ky_hieu": "81/2006/QH11", "tinh_trang": "Hết hiệu lực", "ngay_hieu_luc": "2007-07-01"}
        self.assertTrue(export._trong_pham_vi(row, {"81/2006/QH11"}))

    def test_khong_co_so_thi_xet_theo_ngay_hieu_luc(self):
        row = {"so_ky_hieu": None, "tinh_trang": "Hết hiệu lực", "ngay_hieu_luc": "2006-03-30"}
        self.assertFalse(export._trong_pham_vi(row, set()))

    def test_chinh_thuc_cu_chi_them_khi_vbpl_con_hieu_luc(self):
        rows = [
            {"nguon": "chinh_phu", "url": "u1", "so_ky_hieu": "10/2019/TT-BCA", "loai": "Thông tư",
             "trich_yeu": "x", "co_quan_ban_hanh": "", "ngay_ban_hanh": "2019-03-01", "ngay_hieu_luc": ""},
        ]
        merged = export._merge_chinh_thuc([], rows, [{"so_ky_hieu": "10/2019/TT-BCA", "tinh_trang": "Hết hiệu lực"}])
        self.assertEqual(merged, [])
        merged = export._merge_chinh_thuc([], rows, [{"so_ky_hieu": "10/2019/TT-BCA", "tinh_trang": "Còn hiệu lực"}])
        self.assertEqual(len(merged), 1)


if __name__ == "__main__":
    unittest.main()
