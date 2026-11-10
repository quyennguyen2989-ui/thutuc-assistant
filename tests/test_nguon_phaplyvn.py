"""Kiểm thử bộ đọc vanban.phaplyvn.com bằng trang mẫu (không gọi mạng).

Chạy: python -m unittest tests.test_nguon_phaplyvn
"""

import json
import tempfile
import unittest
from pathlib import Path

from crawler import nguon_phaplyvn

BASE = "https://vanban.phaplyvn.com"
LIST_HTML = b'<a href="/vb/luat-ho-tich-so-03-2026-qh16-x">a</a><a href="/vb/thong-tu-ve-xuat-canh-so-1-2026">b</a><a href="/vb/luat-ho-tich-so-03-2026-qh16-x">dup</a>'
DOC_HTML = (
    "<html><script>var a=1;</script><body><h1>Luật Hộ tịch</h1>"
    "<p>Điều 1. Phạm vi điều chỉnh. Luật này quy định về hộ tịch, đăng ký hộ tịch, cơ sở dữ liệu hộ tịch "
    "và quản lý nhà nước về hộ tịch đối với mọi công dân Việt Nam cư trú trên lãnh thổ nước Cộng hòa xã hội "
    "chủ nghĩa Việt Nam, bảo đảm quyền được xác nhận về hộ tịch theo quy định của pháp luật.</p>"
    "<p>Điều 2. Giải thích từ ngữ. Trong Luật này, các từ ngữ dưới đây được hiểu như sau: hộ tịch là những sự "
    "kiện, thông tin cá nhân được đăng ký, công nhận theo quy định của pháp luật về hộ tịch, bao gồm khai sinh, "
    "kết hôn, khai tử và các sự kiện khác.</p>"
    "<p>Tải tệp văn bản Bản Word</p><div>Số hiệu 03/2026/QH16 Loại văn bản Luật</div></body></html>"
).encode("utf-8")
DOC_KHONG_SO = b"<html><body><p>Dieu 1. Noi dung khong co so hieu.</p></body></html>"


class _Fake:
    """Thay cho Fetcher: trả về nội dung theo đường dẫn."""

    def __init__(self, pages):
        self.pages = pages

    def get_bytes(self, url, accept=None):
        if url in self.pages:
            return self.pages[url]
        raise RuntimeError(f"HTTP 404 khi tải {url}")


class PhaplyvnTest(unittest.TestCase):
    def test_danh_sach_bo_trung_lap(self):
        fake = _Fake({f"{BASE}/?sap_xep=moi": LIST_HTML})
        links = nguon_phaplyvn.danh_sach_moi(fake, 1)
        self.assertEqual(links, [f"{BASE}/vb/luat-ho-tich-so-03-2026-qh16-x", f"{BASE}/vb/thong-tu-ve-xuat-canh-so-1-2026"])

    def test_khop_tu_khoa_theo_duong_dan(self):
        self.assertTrue(nguon_phaplyvn.khop_tu_khoa(f"{BASE}/vb/luat-ho-tich-so-03-2026", ["ho-tich"]))
        self.assertFalse(nguon_phaplyvn.khop_tu_khoa(f"{BASE}/vb/luat-giao-thong", ["ho-tich"]))

    def test_doc_van_ban_lay_so_hieu_va_than(self):
        fake = _Fake({f"{BASE}/vb/x": DOC_HTML})
        so, body = nguon_phaplyvn.doc_van_ban(fake, f"{BASE}/vb/x")
        self.assertEqual(so, "03/2026/QH16")
        self.assertTrue(body.startswith("Điều 1."))
        self.assertNotIn("Tải tệp văn bản", body)
        self.assertNotIn("Số hiệu", body)

    def test_khong_co_so_hieu_thi_bao_loi(self):
        fake = _Fake({f"{BASE}/vb/y": DOC_KHONG_SO})
        with self.assertRaises(ValueError):
            nguon_phaplyvn.doc_van_ban(fake, f"{BASE}/vb/y")

    def test_dong_bo_luu_van_ban_moi_va_bo_qua_da_co(self):
        out = Path(tempfile.mkdtemp())
        url_ok = f"{BASE}/vb/luat-ho-tich-so-03-2026-qh16-x"
        url_loi = f"{BASE}/vb/thong-tu-ve-xuat-canh-so-1-2026"
        fake = _Fake({
            f"{BASE}/?sap_xep=moi": LIST_HTML,
            url_ok: DOC_HTML,
            url_loi: DOC_KHONG_SO,
        })
        done, failed, moi = nguon_phaplyvn.dong_bo(fake, out, ["ho-tich", "xuat-canh"], trang_toi_da=1)
        self.assertEqual((done, failed, moi), (1, 1, 2))
        index = json.loads((out / "index.json").read_text(encoding="utf-8"))
        by_url = {e["url"]: e for e in index}
        self.assertTrue((out / by_url[url_ok]["tep"]).exists())
        self.assertEqual(by_url[url_ok]["nguon"], "phaplyvn")
        self.assertIsNone(by_url[url_loi]["tep"])
        self.assertIn("số hiệu", by_url[url_loi]["ly_do"])

        # Lần sau: văn bản đã có trong chỉ mục không đọc lại.
        done2, failed2, moi2 = nguon_phaplyvn.dong_bo(fake, out, ["ho-tich", "xuat-canh"], trang_toi_da=1)
        self.assertEqual((done2, failed2, moi2), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
