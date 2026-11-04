import unittest

from crawler import normalize


class ChuanSoKyHieuTest(unittest.TestCase):
    def test_doi_chu_cyrillic_giong_latin_ve_latin(self):
        # Cổng ghi "NĐ-СР" và "BTС" bằng chữ Cyrillic, phải đổi về chữ Latin để tra cứu khớp.
        self.assertEqual(normalize.chuan_so_ky_hieu("07/2025/NĐ-СР"), "07/2025/NĐ-CP")
        self.assertEqual(normalize.chuan_so_ky_hieu("51/2025/TT-BTС"), "51/2025/TT-BTC")

    def test_giu_nguyen_so_ky_hieu_da_dung(self):
        self.assertEqual(normalize.chuan_so_ky_hieu("137/2020/NĐ-CP"), "137/2020/NĐ-CP")
        self.assertEqual(normalize.chuan_so_ky_hieu(""), "")


if __name__ == "__main__":
    unittest.main()
