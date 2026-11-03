"""Đối chiếu chéo dữ liệu để kiểm tra trùng và sót (không gọi mạng).

Chạy sau khi xuất dữ liệu:  python -m crawler.doi_chieu
Kết quả in ra màn hình và ghi vào data/doi_chieu.json (không đưa lên trang công khai).

Kiểm tra:
1. Trùng: một số ký hiệu xuất hiện nhiều hơn một dòng trong van_ban.json (sau khi chuẩn hóa).
2. Nguồn chồng chéo: văn bản chính thức được bao nhiêu nguồn chính thức xác nhận.
3. Sót (theo vbpl.vn): văn bản vbpl.vn thuộc từ khóa giai đoạn nhưng không có trong nguồn chính thức nào.
4. Chưa có trạng thái: văn bản chính thức chưa đối chiếu được với vbpl.vn.
5. Toàn văn: văn bản chính thức chưa có chữ trong thư mục nguon_text.
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from . import export, nguon_chinh_thuc, store, vbpl, vbpl_sync

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "thutuc.db"
DATA_DIR = ROOT / "docs" / "data"
BAO_CAO = ROOT / "data" / "doi_chieu.json"


def _kiem_tra(conn, van_ban, giai_doan):
    keywords = nguon_chinh_thuc.tu_khoa_giai_doan(
        giai_doan, vbpl_sync.load_config()["tu_khoa_tim_van_ban_moi"]
    )
    bao_cao = {"giai_doan": giai_doan, "tu_khoa": keywords}

    # 1. Trùng số ký hiệu trong danh sách xuất
    dem = defaultdict(list)
    for item in van_ban:
        key = export._so_key(item.get("so_ky_hieu"))
        if key:
            dem[key].append(item.get("nguon", ""))
    trung = {key: nguon for key, nguon in dem.items() if len(nguon) > 1}
    bao_cao["trung_so_ky_hieu"] = trung

    # 2. Nguồn chính thức: số văn bản theo nguồn và số văn bản được nhiều nguồn xác nhận
    chinh_thuc = store.load_chinh_thuc(conn)
    theo_nguon = Counter(row["nguon"] for row in chinh_thuc)
    cung_so = defaultdict(set)
    for row in chinh_thuc:
        cung_so[export._so_key(row["so_ky_hieu"])].add(row["nguon"])
    bao_cao["so_van_ban_chinh_thuc"] = dict(theo_nguon)
    bao_cao["xac_nhan_boi_nhieu_nguon"] = sorted(k for k, v in cung_so.items() if len(v) > 1)
    bao_cao["giai_doan_cua_van_ban"] = dict(Counter(row["giai_doan"] for row in chinh_thuc))

    # 3. Sót theo vbpl.vn: văn bản vbpl thuộc phạm vi từ khóa nhưng không có trong nguồn chính thức nào
    chinh_thuc_keys = set(cung_so)
    vbpl_rows = store.load_vbpl(conn)
    thieu = []
    for row in vbpl_rows:
        if not row["so_ky_hieu"]:
            continue
        if not vbpl.is_relevant(row["url"], row["sheet"], keywords):
            continue
        key = export._so_key(row["so_ky_hieu"])
        if key not in chinh_thuc_keys:
            thieu.append({"so_ky_hieu": row["so_ky_hieu"], "tieu_de": row["tieu_de"], "tinh_trang": row["tinh_trang"]})
    bao_cao["vbpl_co_nhung_nguon_chinh_thuc_khong_co"] = thieu

    # 4. Văn bản chính thức chưa có tình trạng vbpl
    vb_keys = {export._so_key(row["so_ky_hieu"]) for row in vbpl_rows if row["tinh_trang"]}
    bao_cao["chinh_thuc_chua_co_tinh_trang_vbpl"] = sorted({
        row["so_ky_hieu"] for row in chinh_thuc if export._so_key(row["so_ky_hieu"]) not in vb_keys
    })

    # 5. Toàn văn
    index_path = DATA_DIR / "nguon_text" / "index.json"
    co_chu = set()
    if index_path.exists():
        for entry in json.loads(index_path.read_text(encoding="utf-8")):
            if entry.get("tep"):
                co_chu.add(entry["url"])
    bao_cao["chinh_thuc_chua_co_toan_van"] = sorted({
        f"{row['so_ky_hieu']} ({row['nguon']})" for row in chinh_thuc if row["url"] not in co_chu
    })
    return bao_cao


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    giai_doan = 3
    for arg in sys.argv:
        if arg.startswith("--giai-doan="):
            giai_doan = int(arg.split("=", 1)[1])
    conn = store.connect(DB_PATH)
    van_ban = json.loads((DATA_DIR / "van_ban.json").read_text(encoding="utf-8"))
    bao_cao = _kiem_tra(conn, van_ban, giai_doan)
    BAO_CAO.write_text(json.dumps(bao_cao, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"Giai đoạn {giai_doan}. Văn bản chính thức theo nguồn: {bao_cao['so_van_ban_chinh_thuc']}")
    print(f"Trùng số ký hiệu trong danh sách xuất: {len(bao_cao['trung_so_ky_hieu'])}")
    print(f"Xác nhận bởi nhiều nguồn chính thức: {len(bao_cao['xac_nhan_boi_nhieu_nguon'])}")
    print(f"Văn bản vbpl.vn theo từ khóa nhưng thiếu ở nguồn chính thức: {len(bao_cao['vbpl_co_nhung_nguon_chinh_thuc_khong_co'])}")
    print(f"Văn bản chính thức chưa có tình trạng vbpl: {len(bao_cao['chinh_thuc_chua_co_tinh_trang_vbpl'])}")
    print(f"Văn bản chính thức chưa có toàn văn: {len(bao_cao['chinh_thuc_chua_co_toan_van'])}")
    print(f"Báo cáo chi tiết: {BAO_CAO}")


if __name__ == "__main__":
    main()
