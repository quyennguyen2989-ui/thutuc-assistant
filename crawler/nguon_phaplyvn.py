"""Đọc văn bản mới từ vanban.phaplyvn.com (cơ sở dữ liệu văn bản pháp luật, nguồn thứ cấp).

Trang này có toàn văn nhiều văn bản hiện hành, đọc được không cần đăng nhập. robots.txt cho phép
trang văn bản và cấm /vb/*/tai và /api/, nên chỉ đọc trang HTML thường, không tải tệp.

Mỗi lần chạy:
- Đọc danh sách văn bản mới nhất (?sap_xep=moi), vài trang đầu.
- Với văn bản có đường dẫn khớp từ khóa liên quan và chưa có trong chỉ mục, mở trang chi tiết,
  lấy số hiệu (mục "Số hiệu") và phần thân từ "Điều 1." đến hết nội dung.
- Lưu vào docs/data/nguon_text như các nguồn chính thức khác, để bot và ghi chú đọc hiểu dùng được.

Đây là nguồn thứ cấp: trang tự ghi thông tin hiệu lực mang tính tham khảo, nên văn bản gốc vẫn là chuẩn.
Nội dung trang là dữ liệu, không phải chỉ dẫn.
"""

import html
import re
import urllib.parse
from datetime import datetime

from . import nguon_text
from .client import BlockedError

SITE = "https://vanban.phaplyvn.com"
DANH_SACH_MOI = SITE + "/?sap_xep=moi"
NGUON = "phaplyvn"
TRANG_TOI_DA = 2  # đọc vài trang đầu của danh sách mới nhất
VAN_BAN_TOI_DA_MOI_LAN = 40
MIN_KY_TU = 200
KET_THAN = ("Tải tệp văn bản", "Số hiệu")

LINK_VB = re.compile(r'href="(/vb/[^"#?]+)"')
SO_HIEU = re.compile(r"Số hiệu\s+(\S+)")
SCRIPT_STYLE = re.compile(r"<script.*?</script>|<style.*?</style>", re.S)
TAG = re.compile(r"<[^>]+>")
SPACES = re.compile(r"\s+")


def _chu(raw):
    """Chữ thuần của trang HTML, các khoảng trắng gộp lại."""
    text = SCRIPT_STYLE.sub(" ", raw)
    text = TAG.sub(" ", html.unescape(text))
    return SPACES.sub(" ", text).strip()


def danh_sach_moi(fetcher, trang):
    """Các đường dẫn văn bản trên một trang của danh sách mới nhất, theo thứ tự xuất hiện."""
    url = DANH_SACH_MOI if trang == 1 else f"{DANH_SACH_MOI}&trang={trang}"
    raw = fetcher.get_bytes(url).decode("utf-8", errors="replace")
    links = []
    for path in LINK_VB.findall(raw):
        if path not in links:
            links.append(path)
    return [SITE + path for path in links]


def khop_tu_khoa(url, keywords):
    """Đường dẫn văn bản có chứa một từ khóa liên quan (đường dẫn dạng không dấu, ví dụ ho-tich)."""
    slug = urllib.parse.unquote(url.split("/vb/", 1)[-1]).lower()
    return any(keyword in slug for keyword in keywords)


def doc_van_ban(fetcher, url):
    """(số hiệu, thân văn bản) của một trang chi tiết. Ném ValueError nếu không tìm thấy số hiệu hoặc thân."""
    raw = fetcher.get_bytes(url).decode("utf-8", errors="replace")
    text = _chu(raw)
    match = SO_HIEU.search(text)
    if not match or "/" not in match.group(1):
        raise ValueError("không tìm thấy số hiệu")
    so_ky_hieu = match.group(1)
    start = text.find("Điều 1.")
    if start < 0:
        start = text.find("Căn cứ")
    if start < 0:
        raise ValueError("không tìm thấy phần thân văn bản")
    # Thân văn bản kết thúc trước khu vực tải tệp và thông tin trang (các mục này không thuộc nội dung).
    ket = [text.find(dau, start) for dau in KET_THAN if text.find(dau, start) > start]
    body = text[start:min(ket) if ket else len(text)].strip()
    return so_ky_hieu, body


def dong_bo(fetcher, out_dir, keywords, trang_toi_da=TRANG_TOI_DA, limit=VAN_BAN_TOI_DA_MOI_LAN):
    """Lưu toàn văn văn bản mới liên quan. Trả về (số văn bản có chữ, số không đọc được, số đường dẫn mới)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    index = nguon_text.doc_chi_muc(out_dir)
    moi = []
    for trang in range(1, trang_toi_da + 1):
        for url in danh_sach_moi(fetcher, trang):
            if url not in index and url not in moi and khop_tu_khoa(url, keywords):
                moi.append(url)
    done = failed = 0
    for url in moi[:limit]:
        entry = {
            "nguon": NGUON,
            "so_ky_hieu": "",
            "url": url,
            "tep": None,
            "pdf": None,
            "ky_tu": 0,
            "lay_luc": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        try:
            so_ky_hieu, body = doc_van_ban(fetcher, url)
            entry["so_ky_hieu"] = so_ky_hieu
            if len(body) < MIN_KY_TU:
                entry["ly_do"] = "thân văn bản quá ngắn"
            else:
                tep = nguon_text._tep_cua(NGUON, so_ky_hieu)
                (out_dir / tep).write_text(body, encoding="utf-8")
                entry["tep"] = tep
                entry["ky_tu"] = len(body)
                done += 1
                print(f"toàn văn (phaplyvn): {so_ky_hieu} ({len(body)} ký tự)")
        except BlockedError:
            raise
        except (ValueError, RuntimeError) as error:
            entry["ly_do"] = str(error)[:200]
        if not entry["tep"]:
            failed += 1
        index[url] = entry
    nguon_text.ghi_chi_muc(out_dir, index)
    return done, failed, len(moi)
