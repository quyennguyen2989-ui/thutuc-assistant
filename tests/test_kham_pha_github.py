"""Kiểm thử việc đẩy kết quả tìm văn bản lên GitHub (không gọi mạng).

Chạy: python -m unittest tests.test_kham_pha_github
"""

import base64
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from crawler import kham_pha_github


class DayTepTest(unittest.TestCase):
    def test_tep_chua_co_thi_tao_moi_khong_kem_sha(self):
        with mock.patch.object(kham_pha_github, "_yeu_cau", side_effect=[(404, None), (201, {})]) as yc:
            da_day = kham_pha_github.day_tep("tok", b"{}", "thong diep")

        self.assertTrue(da_day)
        method, url, token, body = yc.call_args_list[1].args
        self.assertEqual(method, "PUT")
        self.assertTrue(url.endswith("/contents/data/vbpl_kham_pha.json"))
        self.assertNotIn("sha", body)
        self.assertEqual(base64.b64decode(body["content"]), b"{}")
        self.assertEqual(body["branch"], "main")

    def test_noi_dung_khong_doi_thi_khong_day(self):
        hien_tai = {"sha": "abc", "content": base64.encodebytes(b'{"a": 1}').decode("ascii")}
        with mock.patch.object(kham_pha_github, "_yeu_cau", return_value=(200, hien_tai)) as yc:
            da_day = kham_pha_github.day_tep("tok", b'{"a": 1}', "thong diep")

        self.assertFalse(da_day)
        self.assertEqual(yc.call_count, 1)

    def test_noi_dung_doi_thi_day_kem_sha_cu(self):
        hien_tai = {"sha": "abc", "content": base64.b64encode(b"cu").decode("ascii")}
        with mock.patch.object(kham_pha_github, "_yeu_cau", side_effect=[(200, hien_tai), (200, {})]) as yc:
            da_day = kham_pha_github.day_tep("tok", b"moi", "thong diep")

        self.assertTrue(da_day)
        self.assertEqual(yc.call_args_list[1].args[3]["sha"], "abc")


class DocTokenTest(unittest.TestCase):
    def test_doc_token_va_bo_khoang_trang(self):
        with tempfile.TemporaryDirectory() as tmp:
            duong_dan = Path(tmp) / "token.txt"
            duong_dan.write_text("github_pat_abc\n", encoding="utf-8")
            self.assertEqual(kham_pha_github.doc_token(duong_dan), "github_pat_abc")

    def test_token_trong_thi_bao_loi(self):
        with tempfile.TemporaryDirectory() as tmp:
            duong_dan = Path(tmp) / "token.txt"
            duong_dan.write_text("  \n", encoding="utf-8")
            with self.assertRaises(kham_pha_github.LoiGitHub):
                kham_pha_github.doc_token(duong_dan)


if __name__ == "__main__":
    unittest.main()
