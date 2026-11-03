"""Kiểm thử bộ thu thập thủ tục của Cổng Dịch vụ công Quốc gia (không gọi mạng)."""

import unittest

from crawler import cong_dvc, nguon_chinh_thuc, vbpl_sync

TU_KHOA = nguon_chinh_thuc.tu_khoa_giai_doan(3, vbpl_sync.load_config()["tu_khoa_tim_van_ban_moi"])


class FakeClient:
    """Trả lần lượt các trang đã cho, như API phân trang."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = 0

    def post(self, path, body):
        page = self.pages[self.calls]
        self.calls += 1
        return page


def _muc(so):
    return {"id": f"id-{so}", "code": f"1.{so:06d}", "name": f"Thủ tục {so}"}


class LocThuTucTest(unittest.TestCase):
    def test_thu_tuc_cong_an_thuc_hien_duoc_chon(self):
        item = {"departments": ["Công an cấp Xã"], "departmentPromulgate": "Bộ Tư pháp"}
        self.assertTrue(cong_dvc.do_cong_an(item))

    def test_thu_tuc_bo_tu_phap_khong_co_cong_an_bi_bo(self):
        item = {"departments": ["Ủy ban nhân dân cấp xã"], "departmentPromulgate": "Bộ Tư pháp"}
        self.assertFalse(cong_dvc.do_cong_an(item))

    def test_linh_vuc_dan_cu_duoc_nhan_dien(self):
        self.assertTrue(cong_dvc.trong_linh_vuc({"name": "Đăng ký tạm trú"}, TU_KHOA))
        self.assertTrue(cong_dvc.trong_linh_vuc({"name": "Cấp, cấp đổi, cấp lại thẻ căn cước"}, TU_KHOA))
        self.assertFalse(cong_dvc.trong_linh_vuc({"name": "Cấp giấy phép khai thác khoáng sản"}, TU_KHOA))

    def test_khai_sinh_duoc_chon_khong_can_cong_an(self):
        self.assertTrue(cong_dvc.la_khai_sinh({"name": "Thủ tục đăng ký khai sinh"}))
        self.assertTrue(cong_dvc.la_khai_sinh({"name": "Cấp bản sao Trích lục hộ tịch, bản sao Giấy khai sinh"}))
        self.assertFalse(cong_dvc.la_khai_sinh({"name": "Đăng ký tạm trú"}))

    def test_bien_so_xe_thuoc_linh_vuc_xe(self):
        self.assertTrue(cong_dvc.trong_linh_vuc({"name": "Đăng ký biển số xe"}, TU_KHOA))

    def test_tu_khoa_chung_khong_tinh_la_linh_vuc(self):
        self.assertFalse(cong_dvc.trong_linh_vuc({"name": "Thủ tục hành chính về thuế"}, TU_KHOA))


class PhanTrangTest(unittest.TestCase):
    def test_doc_het_cac_trang(self):
        trang1 = {"items": [_muc(i) for i in range(100)], "lastId": "a", "total": 150}
        trang2 = {"items": [_muc(i) for i in range(100, 150)], "lastId": "b", "total": 150}
        items = cong_dvc.liet_ke(FakeClient([trang1, trang2]))
        self.assertEqual(len(items), 150)

    def test_thieu_so_luong_thi_bao_loi(self):
        trang1 = {"items": [_muc(i) for i in range(100)], "lastId": "a", "total": 300}
        trang2 = {"items": [_muc(i) for i in range(100, 150)], "lastId": "", "total": 300}
        with self.assertRaises(RuntimeError):
            cong_dvc.liet_ke(FakeClient([trang1, trang2]))


class ChuanHoaTest(unittest.TestCase):
    def test_chi_tiet_thanh_cau_truc_cua_tthc(self):
        item = {"id": "uuid-1", "code": "1.116789", "name": "Đăng ký tạm trú", "categories": ["Cư trú"], "state": "ACTIVE"}
        chi_tiet = {
            "name": "Đăng ký tạm trú",
            "executingAgencies": "Công an cấp Xã",
            "executionSteps": [{"description": "- Bước 1: nộp hồ sơ"}, {"description": "- Bước 2: nhận kết quả"}],
            "executionMethods": [{"submissionMethod": "ONLINE", "description": "Ba (03) ngày làm việc"}],
            "executionCases": [{"profileComponents": [{"name": "Tờ khai đăng ký cư trú", "originalQty": 1}]}],
            "resultsDetails": [{"name": "Giấy xác nhận tạm trú"}],
            "legalBasisesDetails": [{"name": "Luật Cư trú số 68/2020/QH14"}],
            "requirementsAndConditions": "Không",
            "fees": [],
            "state": "ACTIVE",
        }
        ban_ghi = cong_dvc.chuan_hoa(item, chi_tiet)
        self.assertEqual(ban_ghi["id"], 1116789)
        self.assertEqual(ban_ghi["ma_thu_tuc"], "1.116789")
        self.assertEqual(ban_ghi["co_quan_thuc_hien"], "Công an cấp Xã")
        self.assertEqual(ban_ghi["thoi_han"], "Ba (03) ngày làm việc")
        self.assertEqual(ban_ghi["thanh_phan_ho_so"], "- Tờ khai đăng ký cư trú")
        self.assertIn("Bước 2", ban_ghi["trinh_tu"])
        self.assertEqual(ban_ghi["can_cu"], ["Luật Cư trú số 68/2020/QH14"])
        self.assertEqual(ban_ghi["yeu_cau"], [])
        self.assertTrue(ban_ghi["hieu_luc_theo_cong"])
        self.assertEqual(ban_ghi["nguon"], "cong_dvc_quoc_gia")

    def test_thieu_thoi_han_thi_ghi_chua_quy_dinh(self):
        item = {"id": "uuid-2", "code": "1.116790", "name": "Đăng ký thường trú", "state": "ACTIVE"}
        ban_ghi = cong_dvc.chuan_hoa(item, {"executionMethods": []})
        self.assertEqual(ban_ghi["thoi_han"], cong_dvc.CHO_TRONG)


if __name__ == "__main__":
    unittest.main()
