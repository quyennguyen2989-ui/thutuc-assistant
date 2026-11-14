"""Kiểm thử đường đẩy một commit và luồng chạy trên server-chat (không gọi mạng, không mở trình duyệt).

Chạy: python -m unittest tests.test_vbpl_may_chu
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from crawler import cong_dvc, kham_pha_github, nguon_trang_thai, store, vbpl_may_chu, vbpl_sync


def _tra_loi_cay(cay_cu_entries):
    """Chuỗi phản hồi GitHub giả lập cho các lượt gọi đọc cây."""
    return {"tree": cay_cu_entries, "truncated": False}


class DayNhieuTepTest(unittest.TestCase):
    def test_mot_commit_va_bo_qua_tep_khong_doi(self):
        cu = kham_pha_github.blob_sha(b"giu nguyen")
        cay = [{"path": "a.txt", "type": "blob", "sha": cu}, {"path": "b.txt", "type": "blob", "sha": "x"}]
        tra_loi = [
            (200, {"object": {"sha": "head1"}}),                 # GET ref
            (200, {"tree": {"sha": "cay1"}}),                    # GET commit
            (200, _tra_loi_cay(cay)),                            # GET cây
            (201, {"sha": "blob-b"}),                            # POST blob b.txt
            (201, {"sha": "cay2"}),                              # POST trees
            (201, {"sha": "commit2"}),                           # POST commits
            (200, {}),                                           # PATCH ref
        ]
        with mock.patch.object(kham_pha_github, "_yeu_cau", side_effect=tra_loi) as yc:
            so = kham_pha_github.day_nhieu_tep("tok", {"a.txt": b"giu nguyen", "b.txt": b"moi"}, "thong diep")

        self.assertEqual(so, 1)
        methods = [call.args[0] for call in yc.call_args_list]
        self.assertEqual(methods.count("POST"), 3)  # một blob, một cây, một commit
        self.assertEqual(methods[-1], "PATCH")
        self.assertEqual(yc.call_args_list[-2].args[3]["parents"], ["head1"])

    def test_khong_doi_gi_thi_khong_tao_commit(self):
        cay = [{"path": "a.txt", "type": "blob", "sha": kham_pha_github.blob_sha(b"x")}]
        tra_loi = [(200, {"object": {"sha": "h"}}), (200, {"tree": {"sha": "t"}}), (200, _tra_loi_cay(cay))]
        with mock.patch.object(kham_pha_github, "_yeu_cau", side_effect=tra_loi) as yc:
            so = kham_pha_github.day_nhieu_tep("tok", {"a.txt": b"x"}, "thong diep")

        self.assertEqual(so, 0)
        self.assertEqual(yc.call_count, 3)

    def test_xung_dot_thi_khong_ghi_de(self):
        cay = [{"path": "data/thutuc.db", "type": "blob", "sha": "moi-hon"}]
        tra_loi = [(200, {"object": {"sha": "h"}}), (200, {"tree": {"sha": "t"}}), (200, _tra_loi_cay(cay))]
        with mock.patch.object(kham_pha_github, "_yeu_cau", side_effect=tra_loi):
            with self.assertRaises(kham_pha_github.LoiGitHub):
                kham_pha_github.day_nhieu_tep(
                    "tok", {"data/thutuc.db": b"ban moi"}, "thong diep", sha_cu={"data/thutuc.db": "cu"},
                )


class DauHieuMayChuTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "thutuc.db")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_chua_co_dau_hieu_thi_chua_doc(self):
        from datetime import date
        self.assertFalse(vbpl_sync.may_chu_da_doc(self.conn, date(2026, 11, 13)))

    def test_lech_mot_ngay_do_mui_gio_van_la_da_doc(self):
        from datetime import date
        store.set_state(self.conn, vbpl_sync.MAY_CHU_STATE, "2026-11-13")
        self.assertTrue(vbpl_sync.may_chu_da_doc(self.conn, date(2026, 11, 13)))
        self.assertTrue(vbpl_sync.may_chu_da_doc(self.conn, date(2026, 11, 12)))
        self.assertTrue(vbpl_sync.may_chu_da_doc(self.conn, date(2026, 11, 14)))
        self.assertFalse(vbpl_sync.may_chu_da_doc(self.conn, date(2026, 11, 11)))
        self.assertFalse(vbpl_sync.may_chu_da_doc(self.conn, date(2026, 11, 15)))


class CanhBaoServerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "thutuc.db")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def _chay_vbpl(self, run_at):
        from crawler import update, vbpl_text
        ghi = nguon_trang_thai.Ghi(self.conn, run_at)
        with mock.patch.object(vbpl_sync, "sync", return_value=(0, 0, None, 0)), \
                mock.patch.object(vbpl_text, "sync_texts", return_value=0):
            update._sync_vbpl(self.conn, run_at, ghi, kiem_tra_may_chu=True)
        return ghi.ket_qua["vbpl"]["trang_thai"]

    def test_server_luon_luu_toan_van_du_da_co_dau_hieu(self):
        from crawler import update, vbpl_text
        store.set_state(self.conn, vbpl_sync.MAY_CHU_STATE, "2026-11-14")
        self.conn.commit()
        ghi = nguon_trang_thai.Ghi(self.conn, "2026-11-14T18:00:00+07:00")
        with mock.patch.object(vbpl_sync, "sync", return_value=(0, 0, None, 0)), \
                mock.patch.object(vbpl_text, "sync_texts", return_value=0) as texts:
            update._sync_vbpl(self.conn, "2026-11-14T18:00:00+07:00", ghi)
        texts.assert_called_once()

    def test_server_khong_tu_bao_loi(self):
        from crawler import update
        run_at = "2026-11-14T01:00:00+07:00"
        ghi = nguon_trang_thai.Ghi(self.conn, run_at)
        from crawler import vbpl_text
        with mock.patch.object(vbpl_sync, "sync", return_value=(0, 0, None, 0)), \
                mock.patch.object(vbpl_text, "sync_texts", return_value=0):
            update._sync_vbpl(self.conn, run_at, ghi)
        self.assertEqual(ghi.ket_qua["vbpl"]["trang_thai"], nguon_trang_thai.OK)

    def test_server_chua_doc_hom_nay_thi_bao_loi(self):
        self.assertEqual(self._chay_vbpl("2026-11-14T08:00:00+07:00"), nguon_trang_thai.LOI)

    def test_server_da_doc_thi_khong_bao_loi(self):
        store.set_state(self.conn, vbpl_sync.MAY_CHU_STATE, "2026-11-14")
        self.conn.commit()
        self.assertEqual(self._chay_vbpl("2026-11-14T08:00:00+07:00"), nguon_trang_thai.OK)


class CongDvcTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.conn = store.connect(Path(self._tmp.name) / "thutuc.db")

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def test_ci_bo_qua_khi_server_da_dong_bo_hom_nay(self):
        from crawler import cong_dvc, update
        store.set_state(self.conn, cong_dvc.MAY_CHU_STATE, "2026-11-14")
        self.conn.commit()
        ghi = nguon_trang_thai.Ghi(self.conn, "2026-11-14T08:00:00+07:00")
        with mock.patch.object(cong_dvc, "dong_bo") as dong_bo:
            update._sync_cong_dvc(self.conn, "2026-11-14T08:00:00+07:00", ghi, tin_may_chu=True)

        dong_bo.assert_not_called()
        self.assertEqual(ghi.ket_qua["cong_dvc_quoc_gia"]["trang_thai"], nguon_trang_thai.OK)

    def test_server_luon_dong_bo(self):
        from crawler import cong_dvc, update
        store.set_state(self.conn, cong_dvc.MAY_CHU_STATE, "2026-11-14")
        self.conn.commit()
        ghi = nguon_trang_thai.Ghi(self.conn, "2026-11-14T01:00:00+07:00")
        with mock.patch.object(cong_dvc, "dong_bo", return_value=(7094, 146, 0)) as dong_bo:
            update._sync_cong_dvc(self.conn, "2026-11-14T01:00:00+07:00", ghi)

        dong_bo.assert_called_once()


class ChayTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        dvc = mock.patch.object(vbpl_may_chu.update.cong_dvc, "dong_bo", return_value=(0, 0, 0))
        dvc.start()
        self.addCleanup(dvc.stop)
        self.goc = Path(self._tmp.name) / "repo"
        self.goc.mkdir()
        db = Path(self._tmp.name) / "mau.db"
        conn = store.connect(db)
        conn.close()
        self.db_bytes = db.read_bytes()
        self.token = Path(self._tmp.name) / "token.txt"
        self.token.write_text("github_pat_test\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _tai_ve(self, duong_dan):
        if duong_dan == vbpl_may_chu.DB_REL:
            return self.db_bytes
        if duong_dan == vbpl_may_chu.INDEX_REL:
            return b"{}"
        raise AssertionError(duong_dan)

    def _sync_gia(self, conn, run_at, ghi):
        ghi.ghi("vbpl", nguon_trang_thai.OK, "đọc 1 văn bản")
        thu_muc = self.goc / vbpl_may_chu.TEXT_REL
        thu_muc.mkdir(parents=True, exist_ok=True)
        (thu_muc / "van-ban-moi.txt").write_text("toàn văn", encoding="utf-8")

    def test_day_toan_van_moi_va_chi_muc_trong_mot_lan(self):
        captured = {}

        def day_gia(token, tep, thong_diep, sha_cu=None, **kwargs):
            captured.update(tep=tep, thong_diep=thong_diep, sha_cu=sha_cu)
            return len(tep)

        with mock.patch.object(vbpl_may_chu, "tai_ve", side_effect=self._tai_ve), \
                mock.patch.object(vbpl_may_chu.update, "_sync_vbpl", side_effect=self._sync_gia), \
                mock.patch.object(kham_pha_github, "day_nhieu_tep", side_effect=day_gia):
            code = vbpl_may_chu.chay(self.goc, str(self.token))

        self.assertEqual(code, 0)
        self.assertIn("docs/data/vbpl_text/van-ban-moi.txt", captured["tep"])
        self.assertNotIn(vbpl_may_chu.INDEX_REL, captured["tep"])  # chỉ mục không đổi thì không đẩy
        self.assertEqual(set(captured["sha_cu"]), {vbpl_may_chu.DB_REL, vbpl_may_chu.INDEX_REL})

    def test_chay_dat_dau_hieu_dvc_sau_khi_thanh_cong(self):
        with mock.patch.object(vbpl_may_chu, "tai_ve", side_effect=self._tai_ve), \
                mock.patch.object(vbpl_may_chu.update, "_sync_vbpl", side_effect=self._sync_gia), \
                mock.patch.object(cong_dvc, "dong_bo", return_value=(7094, 146, 3)):
            vbpl_may_chu.chay(self.goc, None)

        conn = store.connect(self.goc / vbpl_may_chu.DB_REL)
        try:
            self.assertIsNotNone(store.get_state(conn, cong_dvc.MAY_CHU_STATE))
        finally:
            conn.close()

    def test_khong_co_token_thi_khong_day(self):
        with mock.patch.object(vbpl_may_chu, "tai_ve", side_effect=self._tai_ve), \
                mock.patch.object(vbpl_may_chu.update, "_sync_vbpl", side_effect=self._sync_gia), \
                mock.patch.object(kham_pha_github, "day_nhieu_tep") as day:
            code = vbpl_may_chu.chay(self.goc, None)

        self.assertEqual(code, 0)
        day.assert_not_called()

    def test_vbpl_loi_thi_ma_thoat_3(self):
        def sync_loi(conn, run_at, ghi):
            ghi.ghi("vbpl", nguon_trang_thai.BI_CHAN, "HTTP 403")

        with mock.patch.object(vbpl_may_chu, "tai_ve", side_effect=self._tai_ve), \
                mock.patch.object(vbpl_may_chu.update, "_sync_vbpl", side_effect=sync_loi):
            code = vbpl_may_chu.chay(self.goc, None)

        self.assertEqual(code, 3)

    def test_khong_tai_duoc_du_lieu_thi_ma_thoat_2(self):
        def tai_loi(duong_dan):
            raise vbpl_may_chu.LoiTaiVe("mất mạng")

        with mock.patch.object(vbpl_may_chu, "tai_ve", side_effect=tai_loi):
            code = vbpl_may_chu.main(["--goc", str(self.goc)])

        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
