"""Lưu toàn văn các văn bản đang theo dõi để đọc hiểu và làm tài liệu cho bot và skill.

Chỉ tải lại văn bản khi trang vbpl.vn có ngày cập nhật khác lần trước, nên chạy hằng ngày vẫn nhẹ.
Mỗi văn bản là một tệp .txt, và index.json ghi lại đường dẫn, ngày cập nhật và tình trạng.
"""

import json
import re
from pathlib import Path

from . import store, vbpl

INDEX_NAME = "index.json"
# Văn bản TP.HCM chưa có số ký hiệu theo dõi vẫn được lưu toàn văn nếu thuộc các nhóm này.
EXTRA_TEXT_KEYWORDS = ["khu-pho", "to-dan-pho", "ho-tich"]


def file_name(key):
    """'97/2015/QH13' -> '97-2015-QH13.txt'. Với văn bản không có số, dùng tên đường dẫn."""
    return re.sub(r"[^0-9A-Za-zĐđ]+", "-", key).strip("-") + ".txt"


def _key(row):
    return row["so_ky_hieu"] or vbpl.slug_of(row["url"])


def load_index(out_dir):
    path = Path(out_dir) / INDEX_NAME
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_index(out_dir, index):
    path = Path(out_dir) / INDEX_NAME
    path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def sync_texts(conn, out_dir, delay_seconds):
    """Tải toàn văn các văn bản có số ký hiệu đang theo dõi và có ngày cập nhật mới. Trả về số tệp đã ghi."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    index = load_index(out_dir)

    rows = [
        row for row in store.load_vbpl(conn)
        if row["tinh_trang"] and (row["so_ky_hieu"] or vbpl.is_relevant(row["url"], row["sheet"], EXTRA_TEXT_KEYWORDS))
    ]
    todo = [row for row in rows if index.get(_key(row), {}).get("ngay_cap_nhat") != row["ngay_cap_nhat"]]
    by_url = {row["url"]: row for row in todo}
    written = 0

    def save(url, text):
        nonlocal written
        row = by_url[url]
        if text is None:
            return
        key = _key(row)
        (out_dir / file_name(key)).write_text(text, encoding="utf-8")
        index[key] = {
            "url": url,
            "tieu_de": row["tieu_de"],
            "so_ky_hieu": row["so_ky_hieu"],
            "tinh_trang": row["tinh_trang"],
            "ngay_hieu_luc": row["ngay_hieu_luc"],
            "ngay_cap_nhat": row["ngay_cap_nhat"],
            "tep": file_name(key),
        }
        save_index(out_dir, index)
        written += 1

    vbpl.read_full_texts([row["url"] for row in todo], save, delay_seconds=delay_seconds)
    return written
