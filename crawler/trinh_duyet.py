"""Đường dự phòng qua trình duyệt (Chromium không giao diện) khi kết nối trực tiếp bị quá giờ.

Lý do: trên máy chủ CI của GitHub, kết nối trực tiếp tới cổng Dịch vụ công Quốc gia và trang
Công báo TP.HCM thường bị quá giờ, trong khi vbpl.vn đọc được qua trình duyệt. Chỉ dùng khi
kết nối trực tiếp đã thất bại; bị từ chối (401/403/429) vẫn dừng ngay, không thử lại bằng cách khác.
"""

import json

from .client import BlockedError, USER_AGENT

BAT_BUOC_DUNG = (401, 403, 429)


def _kiem_tra_ma(status, url):
    if status in BAT_BUOC_DUNG:
        raise BlockedError(f"HTTP {status} khi tải {url} (qua trình duyệt)")
    if status >= 400:
        raise RuntimeError(f"HTTP {status} khi tải {url} (qua trình duyệt)")


def tai_bytes(url, accept="text/html, application/xml;q=0.9, */*;q=0.8", timeout_ms=90000):
    """Tải nội dung một trang bằng trình duyệt. Trả về bytes."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=USER_AGENT, locale="vi-VN")
            response = context.request.get(url, headers={"Accept": accept}, timeout=timeout_ms)
            _kiem_tra_ma(response.status, url)
            return response.body()
        finally:
            browser.close()


def goi_post_json(url, body, timeout_ms=90000):
    """Gọi API POST JSON bằng trình duyệt. Trả về phần JSON đã giải mã."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=USER_AGENT, locale="vi-VN")
            response = context.request.post(
                url,
                data=json.dumps(body),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=timeout_ms,
            )
            _kiem_tra_ma(response.status, url)
            return json.loads(response.body().decode("utf-8"))
        finally:
            browser.close()
