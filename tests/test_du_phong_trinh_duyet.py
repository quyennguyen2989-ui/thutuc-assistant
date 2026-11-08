"""Kiểm thử đường dự phòng qua trình duyệt khi kết nối trực tiếp bị quá giờ (không gọi mạng thật).

Chạy: python -m unittest tests.test_du_phong_trinh_duyet
"""

import unittest
import urllib.error
from unittest import mock

from crawler import cong_dvc, nguon_chinh_thuc
from crawler.client import BlockedError


def _timeout(*args, **kwargs):
    raise TimeoutError("timed out")


class DvcDuPhongTest(unittest.TestCase):
    def test_quá_giờ_truc_tiep_thi_dung_trinh_duyet(self):
        client = cong_dvc.DvcClient(delay_seconds=0, timeout=1)
        payload = {"code": "OK", "data": {"items": [], "total": 0, "lastId": ""}}
        with mock.patch("crawler.cong_dvc.urllib.request.urlopen", side_effect=_timeout), \
                mock.patch("crawler.cong_dvc.time.sleep"), \
                mock.patch("crawler.trinh_duyet.goi_post_json", return_value=payload) as browser:
            data = client.post(cong_dvc.DANH_SACH_PATH, {"limit": 1})
        self.assertEqual(data, payload["data"])
        browser.assert_called_once()

    def test_trinh_duyet_cung_loi_thi_bao_ca_hai(self):
        client = cong_dvc.DvcClient(delay_seconds=0, timeout=1)
        with mock.patch("crawler.cong_dvc.urllib.request.urlopen", side_effect=_timeout), \
                mock.patch("crawler.cong_dvc.time.sleep"), \
                mock.patch("crawler.trinh_duyet.goi_post_json", side_effect=RuntimeError("đóng")):
            with self.assertRaises(RuntimeError) as ctx:
                client.post(cong_dvc.DANH_SACH_PATH, {"limit": 1})
        self.assertIn("qua trình duyệt", str(ctx.exception))

    def test_bi_tu_choi_thi_khong_thu_trinh_duyet(self):
        client = cong_dvc.DvcClient(delay_seconds=0, timeout=1)
        denied = urllib.error.HTTPError("u", 403, "Forbidden", {}, None)
        with mock.patch("crawler.cong_dvc.urllib.request.urlopen", side_effect=denied), \
                mock.patch("crawler.cong_dvc.time.sleep"), \
                mock.patch("crawler.trinh_duyet.goi_post_json") as browser:
            with self.assertRaises(BlockedError):
                client.post(cong_dvc.DANH_SACH_PATH, {"limit": 1})
        browser.assert_not_called()


class CongBaoDuPhongTest(unittest.TestCase):
    def test_tai_truc_tiep_quá_gio_thi_dung_trinh_duyet(self):
        fetcher = nguon_chinh_thuc.Fetcher(delay_seconds=0, timeout=1)
        with mock.patch("crawler.nguon_chinh_thuc.urllib.request.urlopen", side_effect=_timeout), \
                mock.patch("crawler.nguon_chinh_thuc.time.sleep"), \
                mock.patch("crawler.trinh_duyet.tai_bytes", return_value=b"<html>ok</html>") as browser:
            self.assertEqual(fetcher.get_bytes("https://congbao.hochiminhcity.gov.vn/x"), b"<html>ok</html>")
        browser.assert_called_once()


if __name__ == "__main__":
    unittest.main()
