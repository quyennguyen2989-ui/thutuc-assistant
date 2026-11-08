"""Kiểm thử liên kết vbpl.vn không còn tồn tại: nhận diện, không tính là lỗi tạm thời,
và không đọc lại mỗi ngày trong lần chạy gia tăng.

Chạy: python -m unittest tests.test_vbpl_khong_con
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from crawler import store, vbpl, vbpl_sync

RUN_AT = "2026-11-08T08:00:00+07:00"
CU = "https://vbpl.vn/van-ban/chi-tiet/thong-tu-so-06-2002-tt-bng-huong-dan-cap-gia-han--22094"
KHAC = "https://vbpl.vn/van-ban/chi-tiet/thong-tu-so-35-2010-tt-bca--11111"


class PhanLoaiTest(unittest.TestCase):
    def test_la_khong_con(self):
        self.assertTrue(vbpl.la_khong_con("không còn trên vbpl (HTTP 404)"))
        self.assertFalse(vbpl.la_khong_con("HTTP 403"))
        self.assertFalse(vbpl.la_khong_con(None))


class _Phan(object):
    """Trang giả: goto trả về mã trạng thái, query_selector trả về nội dung chữ."""

    def __init__(self, status, text="", title="Văn bản | CSDL"):
        self._status = status
        self._text = text
        self._title = title

    def goto(self, url, **kwargs):
        return mock.Mock(status=self._status)

    def wait_for_function(self, script, timeout=None):
        return True

    def locator(self, selector):
        raise RuntimeError("không có biểu mẫu cookie")

    def query_selector(self, selector):
        return mock.Mock(inner_text=lambda: self._text)

    def title(self):
        return self._title


class DocTrangTest(unittest.TestCase):
    def test_404_la_khong_con(self):
        info = vbpl._read_one(_Phan(404), CU, 1000)
        self.assertTrue(info["khong_con"])
        self.assertTrue(vbpl.la_khong_con(info["loi"]))

    def test_trang_bao_khong_ton_tai_la_khong_con(self):
        info = vbpl._read_one(_Phan(200, "Văn bản không tồn tại\n\nVề trang chủ"), CU, 1000)
        self.assertTrue(info["khong_con"])
        self.assertTrue(vbpl.la_khong_con(info["loi"]))

    def test_trang_co_noi_dung_van_doc_binh_thuong(self):
        text = "Thông tư số 06/2002/TT-BNG\nTình trạng\nCòn hiệu lực\nNgày có hiệu lực: 01/01/2002\nNgày cập nhật: 02/03/2026"
        info = vbpl._read_one(_Phan(200, text), CU, 1000)
        self.assertIsNone(info["loi"])
        self.assertNotIn("khong_con", info)


class LienKetCuTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_can_kiem_tra_lai_bo_qua_lien_ket_khong_con(self):
        store.upsert_vbpl(self.conn, {"url": CU, "loi": "không còn trên vbpl (HTTP 404)", "kiem_tra_luc": RUN_AT})
        store.upsert_vbpl(self.conn, {"url": KHAC, "loi": "HTTP 403", "kiem_tra_luc": RUN_AT})
        self.conn.commit()
        self.assertEqual(vbpl_sync._can_kiem_tra_lai(self.conn), {KHAC})

    def test_doc_lien_ket_cu_khong_tinh_la_loi(self):
        store.upsert_vbpl(self.conn, {"url": CU, "so_ky_hieu": "06/2002/TT-BNG", "sheet": 1, "loi": "Timeout"})
        self.conn.commit()

        def fake_read(urls, on_result, **kwargs):
            for url in urls:
                on_result(url, {"khong_con": True, "loi": "không còn trên vbpl (HTTP 404)", "http_status": 404})

        with mock.patch("crawler.vbpl.read_detail_pages", side_effect=fake_read):
            so_doc, so_loi, so_khong_con = vbpl_sync.read_statuses(self.conn, RUN_AT, 0, [], only_urls={CU})
        self.conn.commit()

        self.assertEqual((so_doc, so_loi, so_khong_con), (1, 0, 1))
        row = store.load_vbpl(self.conn)[0]
        self.assertEqual(row["so_ky_hieu"], "06/2002/TT-BNG")
        self.assertTrue(vbpl.la_khong_con(row["loi"]))


if __name__ == "__main__":
    unittest.main()
