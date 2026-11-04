"""Kiểm thử đọc tin chỉ đạo của Công an TP.HCM từ HTML mẫu (không gọi mạng).

Chạy: python -m unittest tests.test_nguon_catp
"""

import tempfile
import unittest
from pathlib import Path

from crawler import nguon_catp, store

CONFIG = {
    "trang": [{"url": "https://example/trang", "muc": ["Tin hoạt động", "Cải cách hành chính"]}],
    "tu_khoa_chi_dao": ["chỉ đạo", "triển khai", "quán triệt", "công văn"],
}

# Cấu trúc giống trang thật: tiêu đề mục là <header>; ngày có thể nằm ngoài hoặc trong thẻ liên kết.
PAGE = """
<header>Tin hoạt động</header>
<div class="news"> <div class="row"><div class="col-sm-12">
  <p class="title"><a href='/wps/portal/Home/tin-a'>Hội nghị quán triệt Đề án số 456</a> (31/10/2026)</p>
  <div class="abstract"><p>Đồng chí Giám đốc chủ trì hội nghị, yêu cầu các đơn vị triển khai thực hiện.</p></div>
</div></div></div>
<hr><div class="news"> <div class="row"><div class="col-sm-12">
  <p class="title"><a href='/wps/portal/Home/tin-b'>Lễ khai giảng lớp đào tạo</a> (29/10/2026)</p>
  <div class="abstract"><p>Lớp đào tạo cán bộ khu vực bắt đầu từ sáng nay.</p></div>
</div></div></div>
<header>Cải cách hành chính</header>
<div class="news"> <div class="row"><div class="col-sm-12">
  <p class="title"><a href='/wps/portal/Home/tin-c'>Công văn hướng dẫn cấp căn cước (03/11/2026)</a></p>
  <div class="abstract"><p>Công an Thành phố ban hành công văn hướng dẫn cấp căn cước công dân.</p></div>
</div></div></div>
<p class="title"><a href='/wps/portal/Home/tin-khong-ngay'>Tin không có ngày</a></p>
<header>Gương người tốt việc tốt</header>
<div class="news"> <div class="row"><div class="col-sm-12">
  <p class="title"><a href='/wps/portal/Home/tin-d'>Chỉ đạo khen thưởng người tốt</a> (28/10/2026)</p>
  <div class="abstract"><p>Nội dung ngoài mục được chọn.</p></div>
</div></div></div>
"""


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def get_text(self, url):
        return self.pages[url]


class ParseTest(unittest.TestCase):
    def test_chi_lay_muc_da_chon(self):
        items = nguon_catp.parse_trang(PAGE, ["Tin hoạt động", "Cải cách hành chính"])
        titles = [item["tieu_de"] for item in items]
        self.assertEqual(titles, [
            "Hội nghị quán triệt Đề án số 456",
            "Lễ khai giảng lớp đào tạo",
            "Công văn hướng dẫn cấp căn cước",
        ])
        self.assertNotIn("Chỉ đạo khen thưởng người tốt", titles)

    def test_ngay_va_tom_tat_va_duong_dan(self):
        item = nguon_catp.parse_trang(PAGE, ["Tin hoạt động"])[0]
        self.assertEqual(item["ngay_dang"], "2026-10-31")
        self.assertEqual(item["url"], "https://congan.hochiminhcity.gov.vn/wps/portal/Home/tin-a")
        self.assertIn("chủ trì hội nghị", item["tom_tat"])
        self.assertEqual(item["muc"], "Tin hoạt động")

    def test_ngay_nam_trong_the_lien_ket(self):
        item = nguon_catp.parse_trang(PAGE, ["Cải cách hành chính"])[0]
        self.assertEqual(item["ngay_dang"], "2026-11-03")
        self.assertEqual(item["tieu_de"], "Công văn hướng dẫn cấp căn cước")

    def test_tin_khong_co_ngay_bi_bo_qua(self):
        titles = [item["tieu_de"] for item in nguon_catp.parse_trang(PAGE, ["Cải cách hành chính"])]
        self.assertNotIn("Tin không có ngày", titles)


class FilterTest(unittest.TestCase):
    def test_tu_khoa_khong_phu_thuoc_dau(self):
        item = {"tieu_de": "Hội nghị QUAN TRIET de an", "tom_tat": ""}
        self.assertEqual(nguon_catp.tu_khoa_khop(item, ["quán triệt"]), ["quán triệt"])

    def test_chi_dao_trong_tom_tat_cung_khop(self):
        item = {"tieu_de": "Khám phá nhóm trộm", "tom_tat": "Thực hiện chỉ đạo của Giám đốc"}
        self.assertEqual(nguon_catp.tu_khoa_khop(item, CONFIG["tu_khoa_chi_dao"]), ["chỉ đạo"])

    def test_tin_khong_lien_quan_khong_khop(self):
        item = {"tieu_de": "Lễ khai giảng", "tom_tat": "Lớp đào tạo cán bộ"}
        self.assertEqual(nguon_catp.tu_khoa_khop(item, CONFIG["tu_khoa_chi_dao"]), [])


class DocTinTest(unittest.TestCase):
    def test_doc_tin_loc_va_sap_xep(self):
        ket_qua = nguon_catp.doc_tin(FakeFetcher({"https://example/trang": PAGE}), CONFIG)
        self.assertEqual(ket_qua["tong"], 3)
        self.assertEqual([item["tieu_de"] for item in ket_qua["chi_dao"]],
                         ["Công văn hướng dẫn cấp căn cước", "Hội nghị quán triệt Đề án số 456"])
        self.assertEqual(ket_qua["chi_dao"][1]["tu_khoa"], ["triển khai", "quán triệt"])

    def test_trang_khong_co_muc_nao_bao_loi(self):
        with self.assertRaises(RuntimeError):
            nguon_catp.doc_tin(FakeFetcher({"https://example/trang": "<html>cổng đổi cấu trúc</html>"}), CONFIG)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "thutuc.db")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_ghi_tin_moi_mot_lan_va_khong_trung(self):
        items = [{"url": "u1", "tieu_de": "A", "ngay_dang": "2026-11-01", "muc": "Tin hoạt động",
                  "tom_tat": "x", "tu_khoa": ["chỉ đạo"]}]
        self.assertEqual(store.sync_tin_catp(self.conn, items, "2026-11-04T08:00:00+07:00"), 1)
        self.assertEqual(store.sync_tin_catp(self.conn, items, "2026-11-05T08:00:00+07:00"), 0)
        tin = store.load_tin_catp(self.conn)
        self.assertEqual(len(tin), 1)
        self.assertEqual(tin[0]["tu_khoa"], ["chỉ đạo"])
        self.assertEqual(tin[0]["first_seen"], "2026-11-04T08:00:00+07:00")

    def test_tin_moi_nhat_truoc(self):
        items = [
            {"url": "u1", "tieu_de": "Cũ", "ngay_dang": "2026-10-01", "muc": "m", "tom_tat": "", "tu_khoa": []},
            {"url": "u2", "tieu_de": "Mới", "ngay_dang": "2026-11-02", "muc": "m", "tom_tat": "", "tu_khoa": []},
        ]
        store.sync_tin_catp(self.conn, items, "2026-11-04T08:00:00+07:00")
        self.assertEqual([tin["tieu_de"] for tin in store.load_tin_catp(self.conn)], ["Mới", "Cũ"])


if __name__ == "__main__":
    unittest.main()
