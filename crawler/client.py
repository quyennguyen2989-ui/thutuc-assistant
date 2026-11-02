"""HTTP client cho cổng thông tin.

Gọi chậm, khai báo User-Agent rõ ràng, và dừng ngay khi máy chủ từ chối (403/401/429)
thay vì thử lại liên tục.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

BASE_URL = "https://qlhc-congan.hochiminhcity.gov.vn/wps/"
USER_AGENT = "thutuc-assistant/0.1 (open-source, cong cu tra cuu van ban cho can bo dan cu)"


class BlockedError(RuntimeError):
    """Máy chủ từ chối truy cập. Không thử lại để tránh bị chặn thêm."""


class PortalClient:
    def __init__(self, delay_seconds=1.5, timeout=30.0, retries=3):
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.retries = retries
        self._last_request = 0.0
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def get_json(self, path, params=None):
        query = urllib.parse.urlencode(params or {})
        url = BASE_URL + path + ("?" + query if query else "")
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"},
        )

        last_error = None
        for attempt in range(1, self.retries + 1):
            self._wait_turn()
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
                self._last_request = time.monotonic()
                return json.loads(body)
            except urllib.error.HTTPError as error:
                self._last_request = time.monotonic()
                if error.code in (401, 403, 429):
                    raise BlockedError(f"HTTP {error.code} khi gọi {path}") from error
                last_error = error
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                self._last_request = time.monotonic()
                last_error = error
            time.sleep(2 ** attempt)

        raise RuntimeError(f"Gọi {path} thất bại sau {self.retries} lần: {last_error}")

    def _wait_turn(self):
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
