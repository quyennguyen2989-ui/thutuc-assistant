"""Tin nêu chỉ đạo, triển khai của Công an Thành phố Hồ Chí Minh (congan.hochiminhcity.gov.vn).

Công văn gốc thường không đăng công khai; cổng chủ yếu đăng tin nêu chỉ đạo. Nguồn này đọc trang đầu
của các trang chuyên mục (trang chủ, Tin chuyên ngành, Tin an ninh trật tự), chỉ lấy các mục đã liệt kê
trong catp_config.json, rồi giữ những tin có từ khóa chỉ đạo, triển khai trong tiêu đề hoặc tóm tắt.
Phân trang của cổng dùng đường dẫn dài, nên chỉ đọc trang đầu: mỗi ngày bắt được các tin mới, lịch sử tích lũy dần.
"""

import html
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "catp_config.json"
BASE = "https://congan.hochiminhcity.gov.vn"

HEADER = re.compile(r"<header[^>]*>(.*?)</header>", re.S)
PTITLE = re.compile(r"<p class=\"title\">(.*?)</p>", re.S)
ANCHOR = re.compile(r"<a href='([^']+)'>(.*?)</a>", re.S)
NGAY = re.compile(r"\((\d{2}/\d{2}/\d{4})\)")
ABSTRACT = re.compile(r'<div class="abstract">(.*?)</div>', re.S)


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _clean(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def chuan_hoa(text):
    """Chữ thường, bỏ dấu, Đ thành D: so khớp từ khóa không phụ thuộc dấu."""
    text = text.replace("Đ", "D").replace("đ", "d")
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", text).lower()


def _tin_tu_tieu_de(inner):
    """Đường dẫn, tiêu đề và ngày từ nội dung một thẻ tiêu đề. Ngày có thể nằm trong hoặc ngoài thẻ liên kết.
    Không có ngày hoặc liên kết thì trả về None."""
    anchor = ANCHOR.search(inner)
    ngay = NGAY.search(inner)
    if not anchor or not ngay:
        return None
    tieu_de = _clean(NGAY.sub(" ", anchor.group(2)))
    if not tieu_de:
        return None
    return {
        "url": BASE + anchor.group(1),
        "tieu_de": tieu_de,
        "ngay_dang": datetime.strptime(ngay.group(1), "%d/%m/%Y").date().isoformat(),
    }


def parse_trang(page, muc_can_lay):
    """Các tin nằm trong những mục có tiêu đề thuộc muc_can_lay. Mỗi tin: url, tieu_de, ngay_dang, tom_tat, muc."""
    headers = list(HEADER.finditer(page))
    items = []
    for index, header in enumerate(headers):
        muc = _clean(header.group(1))
        if muc not in muc_can_lay:
            continue
        end = headers[index + 1].start() if index + 1 < len(headers) else len(page)
        for block in page[header.end():end].split('<div class="news">')[1:]:
            for ptitle in PTITLE.finditer(block):
                tin = _tin_tu_tieu_de(ptitle.group(1))
                if tin is None:
                    continue
                # Tóm tắt nằm ngay sau tiêu đề của tin, đến khối tiếp theo thì dừng.
                sau = block[ptitle.end():]
                ket_thuc = PTITLE.search(sau)
                if ket_thuc:
                    sau = sau[:ket_thuc.start()]
                abstract = ABSTRACT.search(sau)
                items.append({
                    **tin,
                    "tom_tat": _clean(abstract.group(1)) if abstract else "",
                    "muc": muc,
                })
    return items


def tu_khoa_khop(item, tu_khoa):
    """Các từ khóa chỉ đạo, triển khai xuất hiện trong tiêu đề hoặc tóm tắt của tin."""
    noi_dung = chuan_hoa(item["tieu_de"] + " " + item["tom_tat"])
    return [key for key in tu_khoa if chuan_hoa(key) in noi_dung]


def doc_tin(fetcher, config):
    """Đọc các trang chuyên mục, trả về {tong, chi_dao}. Lỗi mạng hoặc trang không có mục nào thì báo lỗi."""
    tat_ca = {}
    for trang in config["trang"]:
        page = fetcher.get_text(trang["url"])
        for item in parse_trang(page, trang["muc"]):
            tat_ca.setdefault(item["url"], item)
    if not tat_ca:
        raise RuntimeError("không đọc được tin nào từ các trang chuyên mục (có thể cổng đổi cấu trúc)")

    chi_dao = []
    for item in tat_ca.values():
        khop = tu_khoa_khop(item, config["tu_khoa_chi_dao"])
        if khop:
            chi_dao.append({**item, "tu_khoa": khop})
    chi_dao.sort(key=lambda item: item["ngay_dang"], reverse=True)
    return {"tong": len(tat_ca), "chi_dao": chi_dao}
