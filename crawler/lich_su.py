"""Nạp dần văn bản cũ hơn, mỗi lần một năm, từ mới đến cũ.

Chạy: python -m crawler.lich_su --nam 2024 [--giai-doan=...] (mặc định dùng từ khóa giai đoạn 2)

Mỗi năm là một đợt nạp riêng với đường nền riêng: lần đầu của đợt chỉ ghi nền, không báo văn bản mới.
Sau đó chạy vbpl để kiểm tra tình trạng: văn bản cũ đã hết hiệu lực bị bỏ khỏi dữ liệu hiển thị
(xem export._trong_pham_vi), còn văn bản vẫn hiệu lực được giữ lại.

Mã đợt của năm N là 1000 + N (không trùng với giai đoạn 1 và 2).
"""

import sys
from datetime import datetime
from pathlib import Path

from . import nguon_chinh_thuc, store, vbpl_sync
from .client import BlockedError

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "thutuc.db"


def ma_dot(nam):
    return 1000 + nam


def nap_nam(conn, fetcher, nam, keywords):
    """Nạp các văn bản Công báo Chính phủ có ngày ban hành trong năm `nam`. Trả về (số văn bản liên quan, số mới)."""
    tu_ngay = f"{nam}-01-01"
    tu_den = f"{nam}-12-31"
    found = nguon_chinh_thuc.duyet_cong_bao_chinh_phu(fetcher, keywords, tu_ngay=tu_ngay, tu_den=tu_den)
    run_at = datetime.now().astimezone().isoformat(timespec="seconds")
    new = store.sync_chinh_thuc(conn, "chinh_phu", found["items"], run_at, giai_doan=ma_dot(nam))
    conn.commit()
    return len(found["items"]), new


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    nam = None
    for arg in sys.argv:
        if arg.startswith("--nam="):
            nam = int(arg.split("=", 1)[1])
    if nam is None:
        print("Cách dùng: python -m crawler.lich_su --nam=2024")
        return 2
    if nam >= vbpl_sync.NAM_BAT_DAU_LICH_SU:
        print(f"Năm {nam} thuộc phạm vi nạp chính (từ {vbpl_sync.NAM_BAT_DAU_LICH_SU}), không cần nạp lịch sử.")
        return 0
    conn = store.connect(DB_PATH)
    keywords = nguon_chinh_thuc.tu_khoa_giai_doan(
        3, vbpl_sync.load_config()["tu_khoa_tim_van_ban_moi"]
    )
    try:
        lien_quan, moi = nap_nam(conn, nguon_chinh_thuc.Fetcher(), nam, keywords)
    except BlockedError as error:
        print(f"Bị từ chối khi nạp năm {nam}: {error}. Dừng, thử lại sau.")
        return 2
    print(f"Năm {nam}: {lien_quan} văn bản liên quan, {moi} văn bản mới trong đợt này.")
    print("Tiếp theo: chạy `python -m crawler.update --khong-chinh-thuc` để kiểm tra tình trạng vbpl và xuất dữ liệu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
