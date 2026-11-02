"""Kiểm thử phân tích sitemap, khớp số ký hiệu và đọc tình trạng từ vbpl.vn (không gọi mạng)."""

import tempfile
import unittest
from pathlib import Path

from crawler import store, vbpl

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://vbpl.vn/van-ban/chi-tiet/luat-cu-tru-so-68-2020-qh14--146648</loc>
    <lastmod>2026-04-05</lastmod>
  </url>
  <url>
    <loc>https://vbpl.vn/van-ban/chi-tiet/law-68-2020-qh14--vbpqta_11132</loc>
    <lastmod>2026-04-06</lastmod>
  </url>
</urlset>
"""

DETAIL_TEXT = (
    "Trang chủ > Văn bản quy phạm pháp luật Trung ương > Nghị định 158/2026/NĐ-CP\n"
    "Nghị định 158/2026/NĐ-CP Quy định chi tiết\n"
    "Còn hiệu lực\nNgày có hiệu lực: 01/07/2026\nNgày cập nhật: 29/10/2026\n23 lượt xem"
)


def entry(url, lastmod="2026-01-01", sheet=1):
    return {"url": url, "lastmod": lastmod, "sheet": sheet}


class SitemapTest(unittest.TestCase):
    def test_read_urlset_reads_loc_lastmod_and_sheet(self):
        entries = vbpl.read_urlset(SITEMAP_XML, 1)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["lastmod"], "2026-04-05")
        self.assertEqual(entries[0]["sheet"], 1)

    def test_english_versions_are_skipped(self):
        self.assertTrue(vbpl.is_vietnamese_version("https://vbpl.vn/van-ban/chi-tiet/luat-cu-tru-so-68-2020-qh14--146648"))
        self.assertFalse(vbpl.is_vietnamese_version("https://vbpl.vn/van-ban/chi-tiet/law-68-2020-qh14--vbpqta_11132"))


class NumberMatchTest(unittest.TestCase):
    def test_normalize_number_handles_vietnamese_letters(self):
        self.assertEqual(vbpl.normalize_number("68/2020/QH14"), "68-2020-qh14")
        self.assertEqual(vbpl.normalize_number("49/2026/QĐ-UBND"), "49-2026-qd-ubnd")

    def test_find_by_number_matches_whole_number_only(self):
        entries = [
            entry("https://vbpl.vn/van-ban/chi-tiet/nghi-quyet-so-118-2026-nq-hdnd-abc--1"),
            entry("https://vbpl.vn/van-ban/chi-tiet/nghi-quyet-so-18-2026-nq-hdnd-le-phi-ho-tich--2"),
        ]
        hit = vbpl.find_by_number(entries, "18/2026/NQ-HĐND")
        self.assertIn("so-18-2026", hit["url"])

    def test_find_by_number_skips_english_version(self):
        entries = [
            entry("https://vbpl.vn/van-ban/chi-tiet/law-68-2020-qh14--vbpqta_11132"),
            entry("https://vbpl.vn/van-ban/chi-tiet/luat-cu-tru-so-68-2020-qh14--146648"),
        ]
        hit = vbpl.find_by_number(entries, "68/2020/QH14")
        self.assertTrue(hit["url"].endswith("146648"))

    def test_find_by_number_returns_none_when_absent(self):
        self.assertIsNone(vbpl.find_by_number([entry("https://vbpl.vn/van-ban/chi-tiet/luat-abc--1")], "1/2000/QH1"))


class DiscoverTest(unittest.TestCase):
    keywords = ["cu-tru", "con-dau"]

    def test_local_documents_must_mention_ho_chi_minh_city(self):
        other_province = entry(
            "https://vbpl.vn/van-ban/chi-tiet/nghi-quyet-ve-cu-tru-tinh-khac--1", "2026-06-01", sheet=20
        )
        hcm = entry(
            "https://vbpl.vn/van-ban/chi-tiet/nghi-quyet-ve-cu-tru-tren-dia-ban-thanh-pho-ho-chi-minh--2",
            "2026-06-01", sheet=20,
        )
        found = vbpl.discover([other_province, hcm], self.keywords, "2025-01-01")
        self.assertEqual([hit["url"] for hit in found], [hcm["url"]])

    def test_central_documents_need_only_keyword_and_recent_update(self):
        recent = entry("https://vbpl.vn/van-ban/chi-tiet/nghi-dinh-ve-con-dau--1", "2026-02-13", sheet=1)
        old = entry("https://vbpl.vn/van-ban/chi-tiet/nghi-dinh-ve-con-dau--2", "2019-02-13", sheet=1)
        found = vbpl.discover([recent, old], self.keywords, "2025-01-01")
        self.assertEqual([hit["url"] for hit in found], [recent["url"]])


class DetailTextTest(unittest.TestCase):
    def test_status_and_dates_are_read_from_page_text(self):
        info = vbpl.parse_detail_text(DETAIL_TEXT)
        self.assertEqual(info["tinh_trang"], "Còn hiệu lực")
        self.assertEqual(info["ngay_hieu_luc"], "2026-07-01")
        self.assertEqual(info["ngay_cap_nhat"], "2026-10-29")

    def test_expired_status_is_detected(self):
        text = "Hết hiệu lực Ngày có hiệu lực: 01/01/2016 Ngày cập nhật: 16/01/2026"
        self.assertEqual(vbpl.parse_detail_text(text)["tinh_trang"], "Hết hiệu lực")

    def test_missing_fields_become_none(self):
        info = vbpl.parse_detail_text("Trang lỗi")
        self.assertIsNone(info["tinh_trang"])
        self.assertIsNone(info["ngay_hieu_luc"])


class StoreVbplTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_upsert_keeps_columns_not_in_the_new_row(self):
        url = "https://vbpl.vn/van-ban/chi-tiet/luat-cu-tru-so-68-2020-qh14--146648"
        store.upsert_vbpl(self.conn, {"url": url, "so_ky_hieu": "68/2020/QH14", "tinh_trang": "Còn hiệu lực"})
        store.upsert_vbpl(self.conn, {"url": url, "kiem_tra_luc": "2026-11-02T08:00:00", "loi": "timeout"})

        row = store.load_vbpl(self.conn)[0]
        self.assertEqual(row["tinh_trang"], "Còn hiệu lực")
        self.assertEqual(row["so_ky_hieu"], "68/2020/QH14")
        self.assertEqual(row["loi"], "timeout")


PARTIAL_TEXT = (
    "Luật Phí và lệ phí số 97/2015/QH13 Hết hiệu lực một phần Ngày có hiệu lực: 01/01/2017 "
    "Ngày cập nhật: 08/05/2026 137 lượt xem"
)

HISTORY_TEXT = (
    "Lịch sử văn bản Thời gian Trạng thái Văn bản nguồn "
    "01/01/2026 Văn bản bị sửa đổi, bổ sung Luật Ngân sách nhà nước số 89/2025/QH15 "
    "01/01/2025 Văn bản bị sửa đổi, bổ sung Luật Đường bộ số 35/2024/QH15 "
    "01/07/2019 Văn bản bị bãi bỏ một phần Luật Cạnh tranh số 23/2018/QH14 "
    "01/01/2017 Văn bản có hiệu lực Luật Phí và lệ phí số 97/2015/QH13 "
    "25/11/2015 Văn bản được ban hành Luật Phí và lệ phí số 97/2015/QH13 Tải về"
)


class PartialStatusTest(unittest.TestCase):
    def test_partial_expiry_is_not_cut_to_expired(self):
        info = vbpl.parse_detail_text(PARTIAL_TEXT)
        self.assertEqual(info["tinh_trang"], "Hết hiệu lực một phần")
        self.assertEqual(info["ngay_hieu_luc"], "2017-01-01")


class HistoryTest(unittest.TestCase):
    def test_history_entries_are_read_in_order(self):
        entries = vbpl.parse_history_text(HISTORY_TEXT)
        self.assertEqual(entries[0], {
            "ngay": "2026-01-01",
            "trang_thai": "Văn bản bị sửa đổi, bổ sung",
            "van_ban_nguon": "Luật Ngân sách nhà nước số 89/2025/QH15",
        })
        self.assertEqual(entries[2]["trang_thai"], "Văn bản bị bãi bỏ một phần")
        self.assertEqual(entries[-1]["trang_thai"], "Văn bản được ban hành")
        self.assertEqual(len(entries), 5)

    def test_history_stops_at_issuance_and_ignores_footer(self):
        entries = vbpl.parse_history_text(HISTORY_TEXT)
        self.assertTrue(all("Tải về" not in entry["van_ban_nguon"] for entry in entries))

    def test_missing_history_returns_empty_list(self):
        self.assertEqual(vbpl.parse_history_text("Nội dung văn bản không có mục lịch sử"), [])


class OwnNumberMatchTest(unittest.TestCase):
    def test_document_that_repeals_a_number_is_not_chosen_over_its_own(self):
        entries = [
            {"url": "https://vbpl.vn/van-ban/chi-tiet/nghi-quyet-so-32-2023-nq-hdnd-bai-bo-nghi-quyet-so-07-2017-nq-hdnd-thanh-pho-ho-chi-minh--5", "lastmod": "2026-03-25", "sheet": 25},
            {"url": "https://vbpl.vn/van-ban/chi-tiet/nghi-quyet-so-07-2017-nq-hdnd-le-phi-cu-tru-thanh-pho-ho-chi-minh--6", "lastmod": "2026-03-25", "sheet": 25},
        ]
        hit = vbpl.find_by_number(entries, "07/2017/NQ-HĐND")
        self.assertTrue(hit["url"].endswith("--6"))

    def test_amending_document_is_used_only_when_no_own_document_exists(self):
        entries = [
            {"url": "https://vbpl.vn/van-ban/chi-tiet/luat-sua-doi-bo-sung-mot-so-dieu-cua-luat-cu-tru-so-36-2013-qh13--7", "lastmod": "2026-03-27", "sheet": 1},
        ]
        hit = vbpl.find_by_number(entries, "36/2013/QH13")
        self.assertTrue(hit["url"].endswith("--7"))


class ProvinceMatchTest(unittest.TestCase):
    def test_hcm_document_is_preferred_over_another_province_with_same_number(self):
        entries = [
            {"url": "https://vbpl.vn/van-ban/chi-tiet/nghi-quyet-so-07-2017-nq-hdnd-lai-chau--1", "lastmod": "2026-06-16", "sheet": 20},
            {"url": "https://vbpl.vn/van-ban/chi-tiet/nghi-quyet-so-07-2017-nq-hdnd-le-phi-cu-tru-thanh-pho-ho-chi-minh--2", "lastmod": "2026-06-16", "sheet": 20},
        ]
        hit = vbpl.find_by_number(entries, "07/2017/NQ-HĐND")
        self.assertTrue(hit["url"].endswith("--2"))

    def test_central_document_is_preferred_over_local(self):
        entries = [
            {"url": "https://vbpl.vn/van-ban/chi-tiet/nghi-quyet-16-2011-ubtvqh12-thanh-pho-ho-chi-minh--3", "lastmod": "2026-01-01", "sheet": 14},
            {"url": "https://vbpl.vn/van-ban/chi-tiet/nghi-quyet-16-2011-ubtvqh12--4", "lastmod": "2026-01-01", "sheet": 1},
        ]
        hit = vbpl.find_by_number(entries, "16/2011/UBTVQH12")
        self.assertTrue(hit["url"].endswith("--4"))


class ConsolidatedMatchTest(unittest.TestCase):
    def test_base_law_is_matched_not_the_consolidated_copy(self):
        entries = [
            entry("https://vbpl.vn/van-ban/chi-tiet/van-ban-hop-nhat-so-92-vbhn-vpqh-luat-phi-va-le-phi-so-97-2015-qh13--a9fa1f00"),
            entry("https://vbpl.vn/van-ban/chi-tiet/luat-phi-va-le-phi-so-97-2015-qh13--96119"),
        ]
        hit = vbpl.find_by_number(entries, "97/2015/QH13")
        self.assertTrue(hit["url"].endswith("--96119"))


if __name__ == "__main__":
    unittest.main()
