"""Đọc văn bản từ CSDL quốc gia về pháp luật (vbpl.vn).

Theo robots.txt, trang cho phép /sitemap/ và /van-ban/chi-tiet/, và cấm /api/ và /Pages/.
Vì vậy mô-đun này chỉ làm hai việc:
1. Đọc sitemap để lấy đường dẫn và ngày cập nhật (lastmod). Dùng để phát hiện văn bản mới.
2. Mở trang chi tiết bằng trình duyệt tự động (Playwright) để lấy tình trạng hiệu lực,
   ngày có hiệu lực và ngày cập nhật. Trang được hiển thị bằng JavaScript nên không đọc được
   bằng HTTP thường.
"""

import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from .client import BlockedError, USER_AGENT

SITE = "https://vbpl.vn"
SITEMAP_INDEX_PATH = "/sitemap.xml"
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
# Sitemap 1–12: văn bản trung ương. Sitemap 13–36: văn bản địa phương (gồm TP.HCM).
CENTRAL_SHEETS = range(1, 13)
LOCAL_SHEETS = range(13, 37)
HCM_MARK = "thanh-pho-ho-chi-minh"

# Nhãn có "một phần" phải đứng trước, nếu không sẽ bị cắt thành "Hết hiệu lực".
STATUS_LABELS = r"(Còn hiệu lực một phần|Hết hiệu lực một phần|Còn hiệu lực|Hết hiệu lực|Chưa có hiệu lực)"
STATUS_BEFORE_EFFECTIVE = re.compile(STATUS_LABELS + r"\s*Ngày có hiệu lực")
STATUS_ANY = re.compile(STATUS_LABELS)
# Các trạng thái trong mục "Lịch sử văn bản" của vbpl.vn.
HISTORY_HEAD = "Lịch sử văn bản"
HISTORY_COLUMNS = "Thời gian Trạng thái Văn bản nguồn"
HISTORY_TERMS = (
    "Văn bản bị sửa đổi, bổ sung",
    "Văn bản bị bãi bỏ một phần",
    "Văn bản bị bãi bỏ",
    "Văn bản bị thay thế",
    "Văn bản bị đình chỉ",
    "Văn bản hết hiệu lực",
    "Văn bản có hiệu lực",
    "Văn bản được ban hành",
)
DATE_IN_HISTORY = re.compile(r"(\d{2}/\d{2}/\d{4}) ")
EFFECTIVE = re.compile(r"Ngày có hiệu lực:\s*(\d{2}/\d{2}/\d{4})")
UPDATED = re.compile(r"Ngày cập nhật:\s*(\d{2}/\d{2}/\d{4})")
NUMBER_IN_TEXT = re.compile(r"\d{1,4}/\d{4}/[\w\-]+")


def fetch_text(url, delay_seconds=1.5, timeout=60):
    """Tải một tệp văn bản (sitemap). Dừng ngay khi bị chặn."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    time.sleep(delay_seconds)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code in (401, 403, 429):
            raise BlockedError(f"HTTP {error.code} khi tải {url}") from error
        raise


def sitemap_urls(sheet_numbers):
    return [f"{SITE}/sitemap/{number}.xml" for number in sheet_numbers]


def read_urlset(xml_text, sheet):
    """Trả về danh sách {url, lastmod, sheet} từ một tệp sitemap."""
    root = ET.fromstring(xml_text)
    entries = []
    for node in root.iter(f"{SITEMAP_NS}url"):
        loc = node.findtext(f"{SITEMAP_NS}loc")
        if not loc:
            continue
        lastmod = node.findtext(f"{SITEMAP_NS}lastmod") or ""
        entries.append({"url": loc, "lastmod": lastmod[:10], "sheet": sheet})
    return entries


def slug_of(url):
    """Phần tên văn bản trong đường dẫn, trước dấu '--' và mã định danh."""
    tail = url.rstrip("/").split("/")[-1]
    return tail.split("--")[0].lower()


def is_vietnamese_version(url):
    # Bản tiếng Anh có tiền tố "law-" và mã "vbpqta_..." — bỏ qua.
    slug = slug_of(url)
    return not slug.startswith("law-") and "vbpqta" not in url


def normalize_number(so_ky_hieu):
    """'68/2020/QH14' -> '68-2020-qh14', '49/2026/QĐ-UBND' -> '49-2026-qd-ubnd'."""
    text = so_ky_hieu.lower().replace("đ", "d").replace("/", "-")
    return re.sub(r"\s+", "", text)


def number_in_slug(number, slug):
    return re.search(rf"(?:^|-){re.escape(number)}(?:-|$)", slug) is not None


def is_consolidated(url):
    """Văn bản hợp nhất (VBHN) là bản tổng hợp của văn bản gốc, không phải văn bản gốc."""
    return slug_of(url).startswith("van-ban-hop-nhat")


# Cụm từ cho biết văn bản đang sửa đổi hoặc bãi bỏ văn bản khác, số phía sau không phải số của nó.
MODIFIER_MARKERS = ("-bai-bo-", "-sua-doi-", "-thay-the-", "-dinh-chinh-", "-ngung-hieu-luc-")


def _is_own_number(slug, number):
    """Số có phải là số của chính văn bản (đứng trước mọi cụm sửa đổi, bãi bỏ) không."""
    head = slug
    for marker in MODIFIER_MARKERS:
        index = slug.find(marker)
        if index >= 0:
            head = slug[:index]
    return number_in_slug(number, head)


def _rank(entry):
    """Số ký hiệu có thể trùng giữa các tỉnh: ưu tiên trung ương, rồi TP.HCM, rồi các tỉnh khác."""
    if entry["sheet"] in CENTRAL_SHEETS:
        return 0
    return 1 if HCM_MARK in slug_of(entry["url"]) else 2


KHONG_KHOP_PATH = Path(__file__).resolve().parent / "vbpl_khong_khop.json"
_khong_khop_cache = None


def khong_khop_cap():
    """Các cặp (số ký hiệu đã chuẩn hóa, đường dẫn) không được gán cho nhau.

    Dùng cho trường hợp trang vbpl.vn chỉ nhắc đến số ký hiệu trong tên, không phải văn bản có số ấy.
    """
    global _khong_khop_cache
    if _khong_khop_cache is None:
        if KHONG_KHOP_PATH.exists():
            data = json.loads(KHONG_KHOP_PATH.read_text(encoding="utf-8"))
            _khong_khop_cache = {(normalize_number(item["so_ky_hieu"]), item["url"]) for item in data}
        else:
            _khong_khop_cache = set()
    return _khong_khop_cache


def find_by_number(entries, so_ky_hieu):
    """Tìm văn bản gốc (không phải bản hợp nhất) có số ký hiệu này trong tên.

    Ưu tiên văn bản mang chính số đó (không phải văn bản bãi bỏ hay sửa đổi nó),
    rồi đến văn bản trung ương, TP.HCM, các tỉnh khác. Bỏ các cặp trong vbpl_khong_khop.json.
    """
    number = normalize_number(so_ky_hieu)
    cam = khong_khop_cap()
    matches = [
        entry for entry in entries
        if is_vietnamese_version(entry["url"])
        and not is_consolidated(entry["url"])
        and number_in_slug(number, slug_of(entry["url"]))
        and (number, entry["url"]) not in cam
    ]
    matches.sort(key=lambda entry: (not _is_own_number(slug_of(entry["url"]), number), _rank(entry)))
    return matches[0] if matches else None


def is_relevant(url, sheet, keywords):
    """Văn bản có liên quan đến công việc hay không.

    Sitemap địa phương chứa văn bản của mọi tỉnh, nên chỉ giữ văn bản của TP.HCM.
    """
    if not is_vietnamese_version(url):
        return False
    slug = slug_of(url)
    if sheet in LOCAL_SHEETS and HCM_MARK not in slug:
        return False
    return any(keyword in slug for keyword in keywords)


def discover(entries, keywords, cutoff):
    """Lọc văn bản mới: liên quan theo từ khóa và cập nhật từ ngày cutoff trở đi."""
    return [
        entry for entry in entries
        if entry["lastmod"] >= cutoff and is_relevant(entry["url"], entry["sheet"], keywords)
    ]


def parse_detail_text(text):
    """Lấy tình trạng, ngày có hiệu lực và ngày cập nhật từ chữ của trang chi tiết."""
    text = re.sub(r"\s+", " ", text)
    status = STATUS_BEFORE_EFFECTIVE.search(text) or STATUS_ANY.search(text)
    effective = EFFECTIVE.search(text)
    updated = UPDATED.search(text)
    return {
        "tinh_trang": status.group(1) if status else None,
        "ngay_hieu_luc": _iso(effective.group(1)) if effective else None,
        "ngay_cap_nhat": _iso(updated.group(1)) if updated else None,
    }


def _iso(dd_mm_yyyy):
    return datetime.strptime(dd_mm_yyyy, "%d/%m/%Y").date().isoformat()


def parse_history_text(text):
    """Đọc mục "Lịch sử văn bản": danh sách {ngay, trang_thai, van_ban_nguon} theo thời gian.

    Trang liệt kê mỗi lần sửa đổi, bổ sung, bãi bỏ một phần... kèm ngày và văn bản gây ra.
    Dòng nào không nhận ra trạng thái sẽ ghi "không rõ" và giữ nguyên chữ gốc, không đoán.
    """
    text = re.sub(r"\s+", " ", text)
    start = text.find(HISTORY_HEAD)
    if start < 0:
        return []
    body = text[start + len(HISTORY_HEAD):].replace(HISTORY_COLUMNS, "", 1)
    parts = DATE_IN_HISTORY.split(body)
    entries = []
    for index in range(1, len(parts) - 1, 2):
        rest = parts[index + 1].strip()
        status = next((term for term in HISTORY_TERMS if rest.startswith(term)), None)
        source = rest[len(status):].strip() if status else rest
        source = _cut_footer(source)
        entries.append({
            "ngay": _iso(parts[index]),
            "trang_thai": status or "không rõ",
            "van_ban_nguon": source,
        })
        if status == "Văn bản được ban hành":
            break  # Đây là dòng ban hành của chính văn bản, sau nó là phần chân trang.
    return entries


# Chữ của thanh công cụ trang chi tiết, có thể lẫn vào dòng cuối của lịch sử.
FOOTER_MARKERS = ("Tải về", "Lược đồ", "Văn bản gốc", "Nội dung Thuộc tính", "TRANG THÔNG TIN")


def _cut_footer(text):
    cut = len(text)
    for marker in FOOTER_MARKERS:
        index = text.find(marker)
        if index >= 0:
            cut = min(cut, index)
    return text[:cut].strip()


def read_detail_pages(urls, on_result, delay_seconds=3.0, timeout_ms=60000, history_urls=frozenset()):
    """Mở từng trang chi tiết bằng Chromium không giao diện, rồi gọi on_result(url, info).

    on_result nhận ngay kết quả từng trang, nên nếu bị chặn giữa chừng thì các trang
    trước đó vẫn được lưu. Với các url trong history_urls, đọc thêm mục lịch sử.
    Nếu máy chủ trả về 403/429 thì dừng (BlockedError).
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="vi-VN")
        try:
            for url in urls:
                info = _read_one(page, url, timeout_ms)
                if url in history_urls and not info.get("loi"):
                    info["lich_su"] = _read_history(page, url, timeout_ms)
                on_result(url, info)
                if info.get("http_status") in (403, 429):
                    raise BlockedError(f"HTTP {info['http_status']} khi mở {url}")
                time.sleep(delay_seconds)
        finally:
            browser.close()


def read_full_texts(urls, on_text, delay_seconds=3.0, timeout_ms=60000):
    """Lấy toàn bộ chữ của trang chi tiết (nội dung văn bản) rồi gọi on_text(url, text)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="vi-VN")
        try:
            for url in urls:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_function(
                        "document.body && document.body.innerText.includes('Ngày cập nhật')",
                        timeout=timeout_ms,
                    )
                    main = page.query_selector("main") or page.query_selector("body")
                    on_text(url, main.inner_text())
                except Exception:  # noqa: BLE001 - một văn bản lỗi không làm hỏng cả đợt
                    on_text(url, None)
                time.sleep(delay_seconds)
        finally:
            browser.close()


def _read_history(page, url, timeout_ms):
    """Mở mục Lịch sử của văn bản. Trả về None nếu không đọc được."""
    try:
        page.goto(f"{url}?tabs=lich-su", wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_function(
            f"document.body && document.body.innerText.includes('{HISTORY_HEAD}')",
            timeout=timeout_ms,
        )
        main = page.query_selector("main") or page.query_selector("body")
        return parse_history_text(main.inner_text())
    except Exception:  # noqa: BLE001 - thiếu lịch sử không làm hỏng dữ liệu tình trạng
        return None


# Liên kết cũ: vbpl.vn không còn văn bản ở đường dẫn này (404, hoặc trang báo "Văn bản không tồn tại").
# Khác với lỗi tạm thời, các liên kết này không đọc lại mỗi ngày và không tính vào tỷ lệ lỗi.
KHONG_CON_PREFIX = "không còn trên vbpl"
KHONG_TON_TAI_TEXT = "Văn bản không tồn tại"
DETAIL_READY = "Ngày cập nhật"


def la_khong_con(loi):
    """Lỗi đánh dấu văn bản không còn trên vbpl.vn (liên kết cũ)."""
    return bool(loi) and loi.startswith(KHONG_CON_PREFIX)




def _tu_choi_cookie(page):
    """Bấm "Từ chối" ở biểu mẫu cookie của vbpl.vn (lựa chọn chỉ dùng cookie cần thiết). Không có thì bỏ qua."""
    try:
        nut = page.locator("button").filter(has_text="Từ chối")
        for i in range(nut.count()):
            if nut.nth(i).is_visible():
                nut.nth(i).click(timeout=5000)
                return True
    except Exception:  # noqa: BLE001 - biểu mẫu không hiện thì không cần từ chối
        pass
    return False


def _read_one(page, url, timeout_ms):
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        status_code = response.status if response else None
        if status_code in (403, 429):
            return {"http_status": status_code, "loi": f"HTTP {status_code}"}
        if status_code == 404:
            return {"http_status": 404, "khong_con": True, "loi": f"{KHONG_CON_PREFIX} (HTTP 404)"}
        _tu_choi_cookie(page)
        # Chờ đến khi trang có nội dung văn bản hoặc báo không tồn tại, không chờ hết thời gian như trước.
        page.wait_for_function(
            "document.body && (document.body.innerText.includes('Ngày cập nhật')"
            " || document.body.innerText.includes('Văn bản không tồn tại'))",
            timeout=timeout_ms,
        )
        main = page.query_selector("main") or page.query_selector("body")
        text = main.inner_text()
        if DETAIL_READY not in text and KHONG_TON_TAI_TEXT in text:
            return {"http_status": status_code, "khong_con": True, "loi": f"{KHONG_CON_PREFIX} (trang báo không tồn tại)"}
        info = parse_detail_text(text)
        info["tieu_de"] = page.title().split(" | ")[0].strip()
        info["loi"] = None
        info["http_status"] = status_code
        return info
    except Exception as error:  # noqa: BLE001 - ghi nhận lỗi từng trang, không dừng cả đợt
        return {"loi": str(error)[:200], "http_status": None}
