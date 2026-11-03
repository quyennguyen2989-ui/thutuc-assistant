"""Bộ kiến thức cho bot web: gom ghi chú đọc hiểu thành docs/data/kien_thuc/tom_tat.json.

Ghi chú nằm trong kien_thuc/ghi_chu/*.md. Mỗi tệp có phần đầu:

    ---
    so_ky_hieu: 392/2026/NĐ-CP; 385/2026/NĐ-CP
    chu_de: Tên chủ đề ngắn
    ---
    Nội dung ghi chú (chỉ điều khoản đã đọc trong toàn văn).

Chạy: python -m crawler.kien_thuc
Kiểm tra: mỗi ghi chú phải có số ký hiệu; số ký hiệu không có trong danh sách văn bản thì báo cảnh báo.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GHI_CHU_DIR = ROOT / "kien_thuc" / "ghi_chu"
DATA_DIR = ROOT / "docs" / "data"
KET_QUA = DATA_DIR / "kien_thuc" / "tom_tat.json"
GIOI_HAN_GHI_CHU = 20000

PHAN_DAU = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)


def chuan_so(so):
    """Khóa so khớp số ký hiệu: bỏ khoảng trắng, Đ thành D, không phân biệt hoa thường."""
    return re.sub(r"\s+", "", so or "").upper().replace("Đ", "D")


def doc_ghi_chu(path):
    match = PHAN_DAU.match(path.read_text(encoding="utf-8").replace("\r\n", "\n"))
    if not match:
        raise ValueError(f"{path.name}: thiếu phần đầu giữa hai dòng ---")
    meta = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
    so_list = [part.strip() for part in re.split(r"[;,]", meta.get("so_ky_hieu", "")) if part.strip()]
    if not so_list:
        raise ValueError(f"{path.name}: thiếu so_ky_hieu")
    body = match.group(2).strip()
    if not body:
        raise ValueError(f"{path.name}: ghi chú trống")
    if len(body) > GIOI_HAN_GHI_CHU:
        raise ValueError(f"{path.name}: ghi chú dài hơn {GIOI_HAN_GHI_CHU} ký tự")
    return {"file": path.name, "so_ky_hieu": so_list, "chu_de": meta.get("chu_de", ""), "ghi_chu": body}


def build(ghi_chu_dir=GHI_CHU_DIR):
    entries = []
    for path in sorted(ghi_chu_dir.glob("*.md")):
        note = doc_ghi_chu(path)
        for so in note["so_ky_hieu"]:
            entries.append({
                "so_ky_hieu": so,
                "chu_de": note["chu_de"],
                "ghi_chu": note["ghi_chu"],
                "tep": note["file"],
            })
    entries.sort(key=lambda entry: (chuan_so(entry["so_ky_hieu"]), entry["tep"]))
    return entries


def canh_bao_thieu_van_ban(entries, van_ban_path=DATA_DIR / "van_ban.json"):
    """Số ký hiệu trong ghi chú nhưng không có trong danh sách văn bản đã xuất (cảnh báo, không chặn)."""
    if not van_ban_path.exists():
        return []
    known = {chuan_so(item.get("so_ky_hieu")) for item in json.loads(van_ban_path.read_text(encoding="utf-8"))}
    return sorted({entry["so_ky_hieu"] for entry in entries if chuan_so(entry["so_ky_hieu"]) not in known})


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    entries = build()
    KET_QUA.parent.mkdir(parents=True, exist_ok=True)
    KET_QUA.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    thieu = canh_bao_thieu_van_ban(entries)
    print(f"Kiến thức: {len(entries)} mục từ {len({e['tep'] for e in entries})} ghi chú.")
    if thieu:
        print(f"Cảnh báo: số ký hiệu chưa có trong danh sách văn bản: {', '.join(thieu)}")


if __name__ == "__main__":
    main()
