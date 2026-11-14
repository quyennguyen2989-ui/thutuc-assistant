"""Kiểm thử việc không gán nhầm số ký hiệu cho trang vbpl.vn chỉ nhắc đến số đó (không gọi mạng).

Chạy: python -m unittest tests.test_vbpl_khong_khop
"""

import json
import tempfile
import unittest
from pathlib import Path

from crawler import store, vbpl, vbpl_sync, vbpl_text

SAI_URL = json.loads(vbpl.KHONG_KHOP_PATH.read_text(encoding="utf-8"))[0]["url"]  # lấy đúng cặp đã khai báo
DUNG_URL = "https://vbpl.vn/van-ban/chi-tiet/nghi-dinh-so-118-2015-nd-cp-huong-dan-luat-dau-tu--200001"


class TimTheoSoTest(unittest.TestCase):
    def test_trang_nhac_den_so_khong_duoc_gan(self):
        entries = [{"url": SAI_URL, "sheet": 1, "lastmod": "2026-01-01"}]
        self.assertIsNone(vbpl.find_by_number(entries, "118/2015/NĐ-CP"))

    def test_so_cua_chinh_no_van_duoc_tim(self):
        entries = [{"url": SAI_URL, "sheet": 1, "lastmod": "2026-01-01"}]
        hit = vbpl.find_by_number(entries, "83/2016/TT-BTC")
        self.assertEqual(hit["url"], SAI_URL)

    def test_van_ban_dung_van_duoc_gan(self):
        entries = [{"url": SAI_URL, "sheet": 1, "lastmod": "2026-01-01"},
                   {"url": DUNG_URL, "sheet": 1, "lastmod": "2026-01-01"}]
        self.assertEqual(vbpl.find_by_number(entries, "118/2015/NĐ-CP")["url"], DUNG_URL)


class DonSoGanSaiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "thutuc.db")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_bo_so_sai_tren_dong_dung_so(self):
        store.upsert_vbpl(self.conn, {"url": SAI_URL, "so_ky_hieu": "118/2015/NĐ-CP"})
        store.upsert_vbpl(self.conn, {"url": DUNG_URL, "so_ky_hieu": "118/2015/NĐ-CP"})
        self.conn.commit()

        sua = vbpl_sync.don_so_gan_sai(self.conn)
        rows = {row["url"]: row["so_ky_hieu"] for row in store.load_vbpl(self.conn)}

        self.assertEqual(sua, 1)
        self.assertIsNone(rows[SAI_URL])
        self.assertEqual(rows[DUNG_URL], "118/2015/NĐ-CP")


class BoMucGanSaiTest(unittest.TestCase):
    def test_xoa_muc_va_tep_gan_sai(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "118-2015-NĐ-CP.txt").write_text("toàn văn sai", encoding="utf-8")
            (out / "khac.txt").write_text("giữ lại", encoding="utf-8")
            index = {
                "118/2015/NĐ-CP": {"url": SAI_URL, "so_ky_hieu": "118/2015/NĐ-CP", "tep": "118-2015-NĐ-CP.txt"},
                "83/2016/TT-BTC": {"url": SAI_URL, "so_ky_hieu": "83/2016/TT-BTC", "tep": "khac.txt"},
            }
            xoa = vbpl_text.bo_muc_gan_sai(out, index)

            self.assertEqual(xoa, 1)
            self.assertNotIn("118/2015/NĐ-CP", index)
            self.assertIn("83/2016/TT-BTC", index)
            self.assertFalse((out / "118-2015-NĐ-CP.txt").exists())
            self.assertTrue((out / "khac.txt").exists())


if __name__ == "__main__":
    unittest.main()
