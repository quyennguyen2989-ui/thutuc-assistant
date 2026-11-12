"""Kiểm thử mô-đun tìm văn bản mới chạy trên server-chat (không gọi mạng).

Chạy: python -m unittest tests.test_kham_pha_vbpl
"""

import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from crawler import kham_pha_vbpl
from crawler.client import BlockedError

CUTOFF = "2025-01-01"
KEYWORDS = ["luat-cu-tru", "ho-tich"]

ENTRIES = [
    {"url": "https://vbpl.vn/van-ban/chi-tiet/thong-tu-01-2026-tt-bca--aaa", "sheet": 1, "lastmod": "2026-01-05"},
    {"url": "https://vbpl.vn/van-ban/chi-tiet/luat-cu-tru-2026--bbb", "sheet": 1, "lastmod": "2026-03-01"},
    {"url": "https://vbpl.vn/van-ban/chi-tiet/quyet-dinh-ve-ho-tich-thanh-pho-ho-chi-minh--ccc",
     "sheet": 20, "lastmod": "2026-02-01"},
    # Quá cũ so với mốc từ ngày: không được tính là văn bản mới.
    {"url": "https://vbpl.vn/van-ban/chi-tiet/luat-cu-tru-2010--ddd", "sheet": 1, "lastmod": "2024-06-01"},
    # Sơ đồ địa phương nhưng không phải TP.HCM: bỏ qua.
    {"url": "https://vbpl.vn/van-ban/chi-tiet/quyet-dinh-ve-ho-tich-tinh-khac--eee",
     "sheet": 21, "lastmod": "2026-02-01"},
]


class SoKyHieuCanTheoDoiTest(unittest.TestCase):
    def test_gop_so_tu_van_ban_va_can_cu_va_bo_trung(self):
        van_ban = [{"so_ky_hieu": "01/2026/TT-BCA"}, {"so_ky_hieu": ""}, {"so_ky_hieu": "81/2006/QH11"}]
        tthc = [{"can_cu": ["Thông tư 01/2026/TT-BCA và Nghị định 137/2020/NĐ-CP", "không có số"]}]
        self.assertEqual(
            kham_pha_vbpl.so_ky_hieu_can_theo_doi(van_ban, tthc),
            sorted(["01/2026/TT-BCA", "81/2006/QH11", "137/2020/NĐ-CP"]),
        )


class TimVanBanTest(unittest.TestCase):
    def test_khop_so_ky_hieu_va_tu_khoa(self):
        rows = kham_pha_vbpl.tim_van_ban(ENTRIES, ["01/2026/TT-BCA"], KEYWORDS, CUTOFF)
        by_url = {row["url"]: row for row in rows}

        self.assertEqual(by_url[ENTRIES[0]["url"]]["so_ky_hieu"], "01/2026/TT-BCA")
        self.assertTrue(by_url[ENTRIES[1]["url"]]["theo_tu_khoa"])
        self.assertTrue(by_url[ENTRIES[2]["url"]]["theo_tu_khoa"])

    def test_loai_van_ban_cu_va_sai_tinh(self):
        rows = kham_pha_vbpl.tim_van_ban(ENTRIES, [], KEYWORDS, CUTOFF)
        urls = {row["url"] for row in rows}

        self.assertNotIn(ENTRIES[3]["url"], urls)
        self.assertNotIn(ENTRIES[4]["url"], urls)

    def test_moi_duong_dan_mot_dong_va_sap_xep(self):
        rows = kham_pha_vbpl.tim_van_ban(ENTRIES, ["01/2026/TT-BCA"], KEYWORDS, CUTOFF)
        urls = [row["url"] for row in rows]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertEqual(urls, sorted(urls))


class TaiSoDoTest(unittest.TestCase):
    def test_thu_lai_khi_loi_tam_thoi(self):
        xml = "<urlset/>"
        with mock.patch.object(kham_pha_vbpl.vbpl, "fetch_text",
                               side_effect=[urllib.error.URLError("kết nối đóng"), xml]) as fetch, \
                mock.patch.object(kham_pha_vbpl.time, "sleep") as sleep:
            self.assertEqual(kham_pha_vbpl._tai_so_do_mot_tep(7, 0), xml)

        self.assertEqual(fetch.call_count, 2)
        sleep.assert_called_once()

    def test_bi_chan_thi_dung_ngay(self):
        with mock.patch.object(kham_pha_vbpl.vbpl, "fetch_text", side_effect=BlockedError("HTTP 403")) as fetch, \
                mock.patch.object(kham_pha_vbpl.time, "sleep") as sleep:
            with self.assertRaises(BlockedError):
                kham_pha_vbpl._tai_so_do_mot_tep(1, 0)

        self.assertEqual(fetch.call_count, 1)
        sleep.assert_not_called()

    def test_loi_tam_thoi_het_so_lan_thu_thi_nem_loi(self):
        with mock.patch.object(kham_pha_vbpl.vbpl, "fetch_text",
                               side_effect=urllib.error.URLError("503")) as fetch, \
                mock.patch.object(kham_pha_vbpl.time, "sleep"):
            with self.assertRaises(urllib.error.URLError):
                kham_pha_vbpl._tai_so_do_mot_tep(1, 0, lan_thu=3, nghi_giay=0)

        self.assertEqual(fetch.call_count, 3)


class MainTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        (self.dir / "van_ban.json").write_text(json.dumps([{"so_ky_hieu": "01/2026/TT-BCA"}]), encoding="utf-8")
        (self.dir / "tthc.json").write_text(json.dumps({"items": [{"can_cu": []}]}), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _chay(self, tai):
        with mock.patch.object(kham_pha_vbpl, "tai_so_do", side_effect=tai):
            return kham_pha_vbpl.main([
                "--van-ban", str(self.dir / "van_ban.json"),
                "--tthc", str(self.dir / "tthc.json"),
                "--dau-ra", str(self.dir / "vbpl_kham_pha.json"),
            ])

    def test_ghi_ket_qua_khi_thanh_cong(self):
        self.assertEqual(self._chay(lambda delay: ENTRIES), 0)
        ket_qua = json.loads((self.dir / "vbpl_kham_pha.json").read_text(encoding="utf-8"))

        self.assertEqual(ket_qua["so_sanh_duoc"], len(ENTRIES))
        self.assertEqual(ket_qua["so_ky_hieu_da_tim"], 1)
        self.assertIn("tao_luc", ket_qua)
        self.assertTrue(any(row["so_ky_hieu"] == "01/2026/TT-BCA" for row in ket_qua["van_ban"]))

    def test_bi_chan_thi_giu_tep_cu(self):
        (self.dir / "vbpl_kham_pha.json").write_text('{"cu": true}', encoding="utf-8")

        self.assertEqual(self._chay(mock.Mock(side_effect=BlockedError("HTTP 403"))), 2)
        self.assertEqual((self.dir / "vbpl_kham_pha.json").read_text(encoding="utf-8"), '{"cu": true}')

    def test_loi_mang_thi_tra_ma_1(self):
        self.assertEqual(self._chay(mock.Mock(side_effect=urllib.error.URLError("hết giờ"))), 1)
        self.assertFalse((self.dir / "vbpl_kham_pha.json").exists())


if __name__ == "__main__":
    unittest.main()
