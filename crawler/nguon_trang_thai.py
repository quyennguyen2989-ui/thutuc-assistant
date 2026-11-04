"""Trạng thái từng nguồn trong mỗi lần chạy: đọc được, lỗi, bị chặn, hoặc bỏ qua.

Mỗi nguồn ghi một dòng vào bảng nguon_run. Trạng thái được xuất vào meta.json (mục trang_thai_nguon),
để biết nguồn nào lỗi và lần đọc thành công gần nhất. Khi có nguồn lỗi hoặc bị chặn, tiến trình
thoát với mã 3: dữ liệu các nguồn khác vẫn được ghi, còn workflow đánh dấu thất bại để GitHub gửi thông báo.
"""

import os

from . import store
from .nguon_chinh_thuc import TEN_NGUON

OK = "ok"
LOI = "loi"
BI_CHAN = "bi_chan"
BO_QUA = "bo_qua"

# Khi một nguồn được ghi nhiều lần trong cùng lần chạy (ví dụ ba giai đoạn của Công báo), giữ mức nặng hơn.
MUC_DO = {BO_QUA: 0, OK: 1, BI_CHAN: 2, LOI: 3}

TEN = {
    "cong_phong_csqlhc": "Cổng Phòng CSQLHC (Công an TP.HCM)",
    "cong_dvc_quoc_gia": "Cổng Dịch vụ công Quốc gia",
    **TEN_NGUON,
    "toan_van": "Toàn văn văn bản chính thức",
    "vbpl": "vbpl.vn",
    "congan_tin": "Tin Công an TP.HCM (chỉ đạo, triển khai)",
}


def ten(nguon):
    return TEN.get(nguon, nguon)


class Ghi:
    """Ghi trạng thái các nguồn của một lần chạy vào cơ sở dữ liệu, và in tóm tắt cuối lần chạy."""

    def __init__(self, conn, run_at):
        self.conn = conn
        self.run_at = run_at
        self.ket_qua = {}

    def ghi(self, nguon, trang_thai, thong_bao=""):
        cu = self.ket_qua.get(nguon)
        if cu is None:
            self.ket_qua[nguon] = {"trang_thai": trang_thai, "thong_bao": thong_bao}
        else:
            if MUC_DO[trang_thai] > MUC_DO[cu["trang_thai"]]:
                cu["trang_thai"] = trang_thai
            cu["thong_bao"] = "; ".join(t for t in (cu["thong_bao"], thong_bao) if t)
        moi = self.ket_qua[nguon]
        store.log_nguon(self.conn, self.run_at, nguon, moi["trang_thai"], moi["thong_bao"])
        self.conn.commit()

    def co_loi(self):
        return any(item["trang_thai"] in (LOI, BI_CHAN) for item in self.ket_qua.values())

    def tom_tat(self):
        """In bảng trạng thái ra màn hình và, khi chạy trên GitHub Actions, vào phần tóm tắt của lần chạy."""
        dong = [f"| {ten(nguon)} | {item['trang_thai']} | {item['thong_bao']} |"
                for nguon, item in self.ket_qua.items()]
        print("Trạng thái từng nguồn:")
        for nguon, item in self.ket_qua.items():
            print(f"  [{item['trang_thai']}] {ten(nguon)}: {item['thong_bao']}")
        duong_dan = os.environ.get("GITHUB_STEP_SUMMARY")
        if duong_dan:
            with open(duong_dan, "a", encoding="utf-8") as tep:
                tep.write("\n### Trạng thái từng nguồn\n\n| Nguồn | Trạng thái | Chi tiết |\n|---|---|---|\n")
                tep.write("\n".join(dong) + "\n")
