"""Đọc văn bản từ CSDL quốc gia về pháp luật (vbpl.vn).

Theo robots.txt, trang cho phép /sitemap/ và /van-ban/chi-tiet/, và cấm /api/ và /Pages/.
Vì vậy mô-đun này chỉ làm hai việc:
1. Đọc sitemap để lấy đường dẫn và ngày cập nhật (lastmod). Dùng để phát hiện văn bản mới.
2. Mở trang chi tiết bằng trình duyệt tự động (Playwright) để lấy tình trạng hiệu lực,
   ngày có hiệu lực và ngày cập nhật. Trang được hiển thị bằng JavaScript nên không đọc được
   bằng HTTP thường.
"""

import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

from .client import BlockedError, USER_AGENT

SITE = "https://vbpl.vn"
SITEMAP_INDEX_PATH = "/sitemap.xml"
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
# Sitemap 1–12: văn bản trung ương. Sitemap 13–36: văn bản địa phương (gồm TP.HCM).
CENTRAL_SHEETS = range(1, 13)
LOCAL_SHEETS = range(13, 37)
HCM_MARK = "thanh-pho-ho-chi-minh"

STATUS_BEFORE_EFFECTIVE = re.compile(r"(Còn hiệu lực|Hết hiệu lực|Chưa có hiệu lực)\s*Ngày có hiệu lực")
STATUS_ANY = re.compile(r"(Còn hiệu lực|Hết hiệu lực|Chưa có hiệu lực)")
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


def find_by_number(entries, so_ky_hieu):
    """Tìm đường dẫn tiếng Việt có số ký hiệu này trong tên."""
    number = normalize_number(so_ky_hieu)
    matches = [
        entry for entry in entries
        if is_vietnamese_version(entry["url"]) and number_in_slug(number, slug_of(entry["url"]))
    ]
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


def read_detail_pages(urls, on_result, delay_seconds=3.0, timeout_ms=60000):
    """Mở từng trang chi tiết bằng Chromium không giao diện, rồi gọi on_result(url, info).

    on_result nhận ngay kết quả từng trang, nên nếu bị chặn giữa chừng thì các trang
    trước đó vẫn được lưu. Nếu máy chủ trả về 403/429 thì dừng (BlockedError).
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="vi-VN")
        try:
            for url in urls:
                info = _read_one(page, url, timeout_ms)
                on_result(url, info)
                if info.get("http_status") in (403, 429):
                    raise BlockedError(f"HTTP {info['http_status']} khi mở {url}")
                time.sleep(delay_seconds)
        finally:
            browser.close()


def _read_one(page, url, timeout_ms):
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        status_code = response.status if response else None
        if status_code in (403, 429):
            return {"http_status": status_code, "loi": f"HTTP {status_code}"}
        page.wait_for_function(
            "document.body && document.body.innerText.includes('Ngày cập nhật')",
            timeout=timeout_ms,
        )
        main = page.query_selector("main") or page.query_selector("body")
        info = parse_detail_text(main.inner_text())
        info["tieu_de"] = page.title().split(" | ")[0].strip()
        info["loi"] = None
        info["http_status"] = status_code
        return info
    except Exception as error:  # noqa: BLE001 - ghi nhận lỗi từng trang, không dừng cả đợt
        return {"loi": str(error)[:200], "http_status": None}
