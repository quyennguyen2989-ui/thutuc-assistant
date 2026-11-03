"""Kiểm thử ba nguồn chính thức (không gọi mạng): phân tích HTML/RSS, lọc giai đoạn 1, ghi nền và ghi nhận mới."""

import tempfile
import unittest
from pathlib import Path

from crawler import export, nguon_chinh_thuc as nguon, store

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title></title>
  <description><![CDATA[Hợp nhất Thông tư Quy định về cư trú]]></description>
  <link>https://congbao.chinhphu.vn/van-ban/van-ban-hop-nhat-so-1-2026-vbhn-tt-bca-1.htm</link>
  <pubDate>Wed, 28 Oct 2026 00:00:00 GMT</pubDate>
</item>
<item>
  <title></title>
  <description><![CDATA[Quy định về kinh doanh vàng]]></description>
  <link>https://congbao.chinhphu.vn/van-ban/van-ban-khac-2.htm</link>
  <pubDate>Mon, 26 Oct 2026 00:00:00 GMT</pubDate>
</item>
</channel></rss>
"""

CHI_TIET_CHINH_PHU = """<html><head><script type="application/ld+json">
{"@type": "Legislation", "name": "Văn bản hợp nhất số 117/2026/VBHN-NĐ-NHNN hợp nhất Nghị định về vàng"}
</script></head><body>
<p>Ban hành: 28/10/2026</p><p>- Hiệu lực: </p>
</body></html>"""

TPHCM_HANG = """<table><thead><tr><th>Ngày ban hành</th><th>Trích yếu</th></tr></thead><tbody>
<tr>
  <td align="left">21-10-2026</td>
  <td style="text-align: justify;">
    <a href="/cong-bao/van-ban/quyet-dinh/so/85-2026-qd-ubnd/ngay/21-10-2026/noi-dung/50245"><span>Quyết định số 85/2026/QĐ-UBND</span> của <b>Ủy ban nhân dân Thành phố Hồ Chí Minh</b> Quy định về cư trú và các yếu tố khác.
    <div class="doc_nav"><a class="tag" href="/cong-bao/van-ban/quyet-dinh/so/85-2026-qd-ubnd/ngay/21-10-2026/50245">Thuộc tính</a></div>
    </a>
  </td>
  <td align="center"><span style="color: blue">21/10/2026</span></td>
</tr>
</tbody></table>"""

BO_CONG_AN_TRANG = """
<div class="card"><a href="/co-so-du-lieu-van-ban/thong-tu-quy-dinh-ve-can-cuoc-123?tab=fulltext" ><p>3</p><p><span>Thông tư</span> 16/2026/TT-BCA</p></a>
<div><a href="/co-so-du-lieu-van-ban/thong-tu-quy-dinh-ve-can-cuoc-123?tab=fulltext" >Thông tư Quy định về thủ tục cấp thẻ Căn cước</a></div>
<p> Cơ quan ban hành: <span>Bộ Công an</span></p>
<p><span>Ngày ban hành: 06/02/2026</span><br><span>Ngày hiệu lực: 26/03/2026</span></p>
<a href="/co-so-du-lieu-van-ban/thong-tu-quy-dinh-ve-can-cuoc-123?tab=attributes">Thuộc tính</a>
</div>
<div><a href="/co-so-du-lieu-van-ban/nghi-dinh-khac-456?tab=fulltext" ><p>4</p><p><span>Nghị định</span> 1/2026/NĐ-CP</p></a>
<div><a href="/co-so-du-lieu-van-ban/nghi-dinh-khac-456?tab=fulltext">Nghị định Quy định về bảo vệ môi trường</a></div>
<p> Cơ quan ban hành: <span>Chính phủ</span></p><p><span>Ngày ban hành: 01/01/2026</span></p></div>
"""


class ParseTest(unittest.TestCase):
    def test_rss_gives_title_link_and_date(self):
        items = nguon.parse_rss(RSS_XML)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["ten"], "Hợp nhất Thông tư Quy định về cư trú")
        self.assertEqual(items[0]["ngay_ban_hanh"], "2026-10-28")
        self.assertTrue(items[0]["url"].startswith("https://congbao.chinhphu.vn/van-ban/"))

    def test_chi_tiet_chinh_phu_reads_number_and_date(self):
        detail = nguon.parse_chi_tiet_chinh_phu(CHI_TIET_CHINH_PHU)
        self.assertEqual(detail["so_ky_hieu"], "117/2026/VBHN-NĐ-NHNN")
        self.assertEqual(detail["ngay_ban_hanh"], "2026-10-28")
        self.assertEqual(detail["ngay_hieu_luc"], "")

    def test_tphcm_row_gives_official_number_dates_and_agency(self):
        parsed = nguon.parse_cong_bao_tphcm(TPHCM_HANG)
        self.assertEqual(parsed["tong"], 1)
        item = parsed["items"][0]
        self.assertEqual(item["so_ky_hieu"], "85/2026/QĐ-UBND")
        self.assertEqual(item["loai"], "Quyết định")
        self.assertEqual(item["co_quan_ban_hanh"], "Ủy ban nhân dân Thành phố Hồ Chí Minh")
        self.assertEqual(item["trich_yeu"], "Quy định về cư trú và các yếu tố khác.")
        self.assertEqual(item["ngay_ban_hanh"], "2026-10-21")
        self.assertEqual(item["ngay_hieu_luc"], "2026-10-21")
        self.assertTrue(item["url"].endswith("/noi-dung/50245"))

    def test_bo_cong_an_cards_are_split_correctly(self):
        parsed = nguon.parse_bo_cong_an(BO_CONG_AN_TRANG)
        self.assertEqual(parsed["tong"], 2)
        first, second = parsed["items"]
        self.assertEqual(first["so_ky_hieu"], "16/2026/TT-BCA")
        self.assertEqual(first["trich_yeu"], "Thông tư Quy định về thủ tục cấp thẻ Căn cước")
        self.assertEqual(first["co_quan_ban_hanh"], "Bộ Công an")
        self.assertEqual(first["ngay_ban_hanh"], "2026-02-06")
        self.assertEqual(first["ngay_hieu_luc"], "2026-03-26")
        self.assertEqual(second["so_ky_hieu"], "1/2026/NĐ-CP")
        self.assertEqual(second["co_quan_ban_hanh"], "Chính phủ")


class FilterTest(unittest.TestCase):
    def test_giai_doan_1_keeps_procedures_and_residence_only(self):
        keywords = nguon.GIAI_DOAN_1
        self.assertTrue(nguon.phu_hop("Hợp nhất Thông tư Quy định về đăng ký cư trú", keywords))
        self.assertTrue(nguon.phu_hop("Luật Cư trú sửa đổi, bổ sung", keywords))
        self.assertTrue(nguon.phu_hop("Thông tư Quy định về thủ tục cấp thẻ Căn cước", keywords))
        self.assertTrue(nguon.phu_hop("Quyết định công bố thủ tục hành chính sửa đổi", keywords))
        self.assertFalse(nguon.phu_hop("Quy định về kinh doanh vàng", keywords))
        self.assertFalse(nguon.phu_hop("Quy định về sinh trắc học giọng nói", keywords))
        # Chỉ nhắc "cư trú" trong nội dung, không phải chủ đề của văn bản: không lấy.
        self.assertFalse(nguon.phu_hop("Nghị quyết hỗ trợ người hiến máu cư trú trên địa bàn", keywords))

    def test_news_strip_decision_without_year_is_read(self):
        page = ('<marquee><a href="/tin-tuc-tong-hop/quyet-dinh-so-6676-qd-ubnd-abc">Quyết định số 6676/QĐ-UBND '
                'về việc công bố danh mục thủ tục hành chính được sửa đổi, bổ sung lĩnh vực Khoa học</a></marquee>')
        items = nguon.parse_trang_so(page, "/cong-bao/so/346-347/01-11-2026")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["so_ky_hieu"], "6676/QĐ-UBND")
        self.assertEqual(items[0]["loai"], "Quyết định")
        self.assertEqual(items[0]["ngay_ban_hanh"], "2026-11-01")
        self.assertTrue(nguon.phu_hop(items[0]["trich_yeu"], nguon.GIAI_DOAN_1))

    def test_keyword_must_match_whole_words(self):
        self.assertFalse(nguon.phu_hop("Quy định về cư trúc tượng", ["cu-tru"]))
        self.assertTrue(nguon.phu_hop("Luật Cư trú", ["cu-tru"]))

    def test_iso_dates(self):
        self.assertEqual(nguon.iso_tu_ngay("21-10-2026"), "2026-10-21")
        self.assertEqual(nguon.iso_tu_ngay("1/7/2026"), "2026-07-01")
        self.assertEqual(nguon.iso_tu_ngay("không có ngày"), "")


LISTING_HTML = """
<a href="/van-ban/nghi-dinh-so-373-2026-nd-cp-470680.htm" title="Nghị định số 373/2026/NĐ-CP về chuyển đơn vị sự nghiệp" class="img"><img src="x.jpg"></a>
<a href="/van-ban/nghi-dinh-so-373-2026-nd-cp-470680.htm" title="Nghị định số 373/2026/NĐ-CP về chuyển đơn vị sự nghiệp" class="sapo">Nghị định số 373/2026/NĐ-CP về chuyển đơn vị sự nghiệp</a>
<div class="share">Được đăng trong: <a href="/cong-bao/560-47565.htm" title="Công báo số 560 ngày 2026-10-23">Công báo</a></div>
<p>Ban hành: 30/09/2026</p><p>Hiệu lực: 15/11/2026</p>
<a href="/van-ban/nghi-dinh-so-364-2026-nd-cp-470544.htm" title="Nghị định số 364/2026/NĐ-CP về thuế" class="sapo">Nghị định số 364/2026/NĐ-CP về thuế</a>
<p>Ban hành: 01/09/2026</p>
"""


class ListingTest(unittest.TestCase):
    def test_listing_reads_number_title_and_dates_once_per_item(self):
        items = nguon.parse_danh_sach_van_ban(LISTING_HTML)
        self.assertEqual(len(items), 2)
        first, second = items
        self.assertEqual(first["so_ky_hieu"], "373/2026/NĐ-CP")
        self.assertEqual(first["trich_yeu"], "về chuyển đơn vị sự nghiệp")
        self.assertEqual(first["ngay_ban_hanh"], "2026-09-30")
        self.assertEqual(first["ngay_hieu_luc"], "2026-11-15")
        self.assertEqual(second["ngay_ban_hanh"], "2026-09-01")
        self.assertEqual(second["ngay_hieu_luc"], "")


class StoreAndMergeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def _doc(self, so, url, trich="Quy định về cư trú"):
        return {"url": url, "so_ky_hieu": so, "loai": "Thông tư", "trich_yeu": trich,
                "co_quan_ban_hanh": "Bộ Công an", "ngay_ban_hanh": "2026-02-06", "ngay_hieu_luc": ""}

    def test_first_run_is_baseline_second_run_logs_only_new(self):
        first = [self._doc("16/2026/TT-BCA", "https://a.example/1")]
        self.assertEqual(store.sync_chinh_thuc(self.conn, "bo_cong_an", first, "2026-11-03T08:00:00+07:00"), 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0], 0)

        second = first + [self._doc("17/2026/TT-BCA", "https://a.example/2")]
        new = store.sync_chinh_thuc(self.conn, "bo_cong_an", second, "2026-11-04T08:00:00+07:00")
        self.assertEqual(new, 1)
        changes = store.load_changes(self.conn)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["kind"], "chinh_thuc")
        self.assertEqual(changes[0]["diff"]["_ten"], "17/2026/TT-BCA: Quy định về cư trú")
        self.assertEqual(len(store.load_chinh_thuc(self.conn, "bo_cong_an")), 2)

    def test_later_sync_fills_missing_dates_and_logs_corrections(self):
        blank = self._doc("60/2026/TT-BKHCN", "https://a.example/60")
        blank["ngay_hieu_luc"] = ""
        store.sync_chinh_thuc(self.conn, "chinh_phu", [blank], "2026-11-03T08:00:00+07:00")
        self.assertEqual(store.load_changes(self.conn), [])

        filled = dict(blank, ngay_hieu_luc="2026-12-01")
        store.sync_chinh_thuc(self.conn, "chinh_phu", [filled], "2026-11-04T08:00:00+07:00")
        row = store.load_chinh_thuc(self.conn, "chinh_phu")[0]
        self.assertEqual(row["ngay_hieu_luc"], "2026-12-01")
        self.assertEqual(len(store.load_changes(self.conn)), 1)  # sửa/điền dữ liệu được ghi lại
        self.assertEqual(store.load_changes(self.conn)[0]["diff"]["ngay_hieu_luc"]["moi"], "2026-12-01")

    def test_merge_attaches_to_existing_number_and_adds_new_ones(self):
        items = [{"so_ky_hieu": "16/2026/TT-BCA", "nguon": "cong_tu_dong"}]
        rows = [
            {"nguon": "bo_cong_an", "url": "https://a.example/1", "so_ky_hieu": "16/2026/TT-BCA",
             "loai": "Thông tư", "trich_yeu": "Quy định", "co_quan_ban_hanh": "Bộ Công an",
             "ngay_ban_hanh": "2026-02-06", "ngay_hieu_luc": ""},
            {"nguon": "tphcm", "url": "https://b.example/85", "so_ky_hieu": "85/2026/QD-UBND",
             "loai": "Quyết định", "trich_yeu": "Quy định khác", "co_quan_ban_hanh": "UBND",
             "ngay_ban_hanh": "2026-10-21", "ngay_hieu_luc": "2026-10-21"},
        ]
        merged = export._merge_chinh_thuc(items, rows)
        self.assertEqual(len(merged), 2)
        self.assertEqual(len(merged[0]["nguon_chinh_thuc"]), 1)
        added = merged[1]
        self.assertEqual(added["nguon"], "chinh_thuc")
        self.assertEqual(added["so_ky_hieu"], "85/2026/QD-UBND")
        self.assertIsNone(added["hieu_luc_theo_cong"])

    def test_number_key_ignores_spaces_and_d_with_stroke(self):
        self.assertEqual(export._so_key("85/2026/QĐ-UBND"), export._so_key("85/2026/QD-UBND"))
        self.assertEqual(export._so_key(" 16/2026/TT-BCA "), "16/2026/TT-BCA")


if __name__ == "__main__":
    unittest.main()
