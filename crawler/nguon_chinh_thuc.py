"""Đọc văn bản mới từ ba nguồn chính thức, để không bỏ sót hướng dẫn mới.

- Công báo điện tử Chính phủ: RSS "Các văn bản được ban hành mới nhất" (máy đọc được).
- Công báo Thành phố Hồ Chí Minh: trang "Văn bản mới" (HTML) có quyết định UBND và nghị quyết HĐND.
- Cổng Bộ Công an (Hệ thống văn bản): các thẻ văn bản mới trên trang chủ (HTML).
  Không gọi API hay trang danh sách phía client của cổng này, vì cổng có lớp bảo vệ chống bot.

Mỗi nguồn trả về văn bản đã lọc theo từ khóa liên quan, dạng dict thống nhất.
Không suy ra tình trạng hiệu lực ở đây: tình trạng do vbpl.vn quyết định.
"""

import email.utils
import html
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .client import BlockedError

USER_AGENT = "thutuc-assistant/0.1 (open-source, cong cu tra cuu van ban cho can bo dan cu)"
RETRIES = 3

RSS_CHINH_PHU = "https://congbao.chinhphu.vn/cac-van-ban-moi-ban-hanh.rss"
CONG_BAO_TPHCM = "https://congbao.hochiminhcity.gov.vn"
CONG_BAO_TPHCM_VAN_BAN_MOI = CONG_BAO_TPHCM + "/cong-bao/van-ban/van-ban-moi"
BO_CONG_AN = "https://vanban.bocongan.gov.vn"

# Trang đầu của từng nguồn, ghi vào meta.json để giao diện hiển thị nguồn.
DIA_CHI_TRANG = {
    "chinh_phu": "https://congbao.chinhphu.vn/",
    "tphcm": CONG_BAO_TPHCM_VAN_BAN_MOI,
    "bo_cong_an": BO_CONG_AN + "/",
}

TEN_NGUON = {
    "chinh_phu": "Công báo điện tử Chính phủ",
    "tphcm": "Công báo Thành phố Hồ Chí Minh",
    "bo_cong_an": "Cổng Thông tin điện tử Bộ Công an (Hệ thống văn bản)",
}

# Giai đoạn 1: văn bản về cư trú và thủ tục hành chính (khớp theo tên văn bản, không dấu).
# Dùng cụm từ rõ nghĩa, không dùng riêng "cư trú": nhiều văn bản chỉ nhắc "cư trú trên địa bàn" trong nội dung.
# "thu-tuc-hanh-chinh" là từ khóa chung: chỉ lấy khi văn bản thuộc cơ quan công an (xem ngoai_pham_vi_thu_tuc).
# Các lĩnh vực khác (ANTT, vũ khí, con dấu, khu phố...) nằm ở giai đoạn 2.
GIAI_DOAN_1 = [
    "luat-cu-tru",
    "dang-ky-cu-tru",
    "tam-tru",
    "tam-vang",
    "thuong-tru",
    "ho-khau",
    "can-cuoc",
    "thu-tuc-hanh-chinh",
]

# Số trang chi tiết tải thêm tối đa mỗi lần chạy (các văn bản chưa từng thấy).
MAX_CHI_TIET_MOI_LAN = 60

LOAI_VAN_BAN = re.compile(
    r"Thông tư liên tịch|Thông tư|Nghị định|Nghị quyết|Quyết định|Chỉ thị|Pháp lệnh|Luật|Công văn",
    re.IGNORECASE,
)


class Fetcher:
    """Tải trang công khai: chậm, có User-Agent rõ ràng, dừng khi bị từ chối (401/403/429)."""

    def __init__(self, delay_seconds=1.5, timeout=60.0):
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self._last = 0.0

    def get_bytes(self, url, accept="text/html, application/xml;q=0.9, */*;q=0.8"):
        elapsed = time.monotonic() - self._last
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)
        # Đường dẫn có chữ có dấu (ví dụ tiêu đề tin) phải được mã hóa trước khi gửi.
        url = urllib.parse.quote(url, safe=":/?=&%#+@,;[]()'")
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        last_error = None
        try:
            # Trang danh sách có thể chậm; lỗi mạng hoặc quá giờ thì thử lại vài lần, còn bị từ chối thì dừng ngay.
            for attempt in range(1, RETRIES + 1):
                try:
                    with urllib.request.urlopen(request, timeout=self.timeout) as response:
                        return response.read()
                except urllib.error.HTTPError as error:
                    if error.code in (401, 403, 429):
                        raise BlockedError(f"HTTP {error.code} khi tải {url}") from error
                    raise RuntimeError(f"HTTP {error.code} khi tải {url}") from error
                except (urllib.error.URLError, TimeoutError, OSError) as error:
                    last_error = error
                    time.sleep(5 * attempt)
            raise RuntimeError(f"tải {url} thất bại sau {RETRIES} lần: {last_error}")
        finally:
            self._last = time.monotonic()

    def get_text(self, url):
        return self.get_bytes(url).decode("utf-8", errors="replace")


def clean(text):
    """Bỏ thẻ HTML, giải mã thực thể, gộp khoảng trắng."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def slug(text):
    """Chuỗi không dấu, nối bằng gạch ngang, để so khớp từ khóa (cùng kiểu với đường dẫn vbpl.vn)."""
    text = text.replace("Đ", "D").replace("đ", "d")
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def co_cum(slugged, keyword):
    """Từ khóa là một cụm trọn vẹn trong chuỗi đã chuẩn hóa (không khớp giữa một từ)."""
    return re.search(rf"(?:^|-){re.escape(keyword)}(?:-|$)", slugged) is not None


def phu_hop(text, keywords):
    """Văn bản liên quan nếu tên có một từ khóa, khớp theo từng cụm từ (không khớp giữa một từ)."""
    slugged = slug(text)
    return any(co_cum(slugged, keyword) for keyword in keywords)


# Từ khóa chung cho mọi thủ tục hành chính; chỉ giữ khi thủ tục do cơ quan công an thực hiện hoặc ban hành.
THU_TUC_HANH_CHINH = "thu-tuc-hanh-chinh"

# Từ khóa dễ lẫn sang ngành khác (khai sinh của Tư pháp, đăng kiểm xe của Giao thông...):
# chỉ giữ khi văn bản thuộc cơ quan công an, giống thủ tục hành chính chung.
TU_KHOA_CAN_CONG_AN = (
    THU_TUC_HANH_CHINH,
    "moi-sinh", "sinh-con", "khai-sinh",
    "dang-ky-xe", "dang-ky-phuong-tien", "giay-phep-lai-xe",
    "xuat-canh", "nhap-canh", "ho-chieu",
)

# Giai đoạn 3: các đăng ký khác với cơ quan công an mà công dân hay làm khi mới sinh con, đi lại, xuất nhập cảnh.
# Thủ tục chi tiết (hồ sơ, trình tự) chưa có trong danh mục cổng; bot tra cứu bằng toàn văn văn bản.
GIAI_DOAN_3 = [
    "moi-sinh",
    "sinh-con",
    "khai-sinh",
    "dang-ky-xe",
    "dang-ky-phuong-tien",
    "giay-phep-lai-xe",
    "xuat-canh",
    "nhap-canh",
    "ho-chieu",
    "phong-chay",
    "chua-chay",
]


def thuoc_cong_an(ten, so_ky_hieu="", co_quan=""):
    """Văn bản của cơ quan công an: số hiệu có "BCA", cơ quan ban hành hoặc tên có "công an"."""
    dau_hieu = slug(f"{ten} {so_ky_hieu} {co_quan}")
    return co_cum(dau_hieu, "bca") or co_cum(dau_hieu, "cong-an")


# Văn bản giữ theo quyết định của cán bộ dù tên không có dấu hiệu công an
# (xử phạt trục xuất, tạm giữ người, áp giải: do lực lượng công an thực hiện).
GIU_THEO_SO = ("59/2026/NĐ-CP",)


def _khoa_so(so_ky_hieu):
    """Khóa so khớp số ký hiệu: bỏ khoảng trắng, Đ thành D, không phân biệt hoa thường."""
    return re.sub(r"\s+", "", so_ky_hieu or "").upper().replace("Đ", "D")


def ngoai_pham_vi_thu_tuc(ten, so_ky_hieu="", co_quan="", tu_khoa=()):
    """Văn bản của ngành khác: tên chỉ khớp các từ khóa dễ lẫn (TU_KHOA_CAN_CONG_AN) và không thuộc cơ quan công an.

    Tên đã khớp một lĩnh vực cụ thể trong tu_khoa (cư trú, căn cước, con dấu...) thì không bị loại.
    Văn bản trong GIU_THEO_SO luôn được giữ.
    """
    if any(_khoa_so(so_ky_hieu) == _khoa_so(giu) for giu in GIU_THEO_SO):
        return False
    slugged = slug(ten)
    if not any(co_cum(slugged, keyword) for keyword in TU_KHOA_CAN_CONG_AN):
        return False
    if any(co_cum(slugged, keyword) for keyword in tu_khoa if keyword not in TU_KHOA_CAN_CONG_AN):
        return False
    return not thuoc_cong_an(ten, so_ky_hieu, co_quan)


def phu_hop_pham_vi(ten, keywords, so_ky_hieu="", co_quan=""):
    """Phù hợp từ khóa và nằm trong phạm vi công an quản lý dân cư."""
    return phu_hop(ten, keywords) and not ngoai_pham_vi_thu_tuc(ten, so_ky_hieu, co_quan, keywords)


def loc_pham_vi(rows, tu_khoa):
    """Giữ các dòng đã lưu (nguon_chinh_thuc) khớp từ khóa và nằm trong phạm vi công an."""
    return [
        row for row in rows
        if phu_hop_pham_vi(f"{row['so_ky_hieu'] or ''} {row['trich_yeu'] or ''}", tu_khoa,
                           row["so_ky_hieu"] or "", row["co_quan_ban_hanh"] or "")
    ]


def iso_tu_ngay(text):
    """'21/10/2026' hoặc '21-10-2026' thành '2026-10-21'. Không đọc được thì trả về chuỗi rỗng."""
    match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text or "")
    if not match:
        return ""
    day, month, year = (int(part) for part in match.groups())
    return f"{year:04d}-{month:02d}-{day:02d}"


def loai_tu(ten):
    match = LOAI_VAN_BAN.search(ten or "")
    if not match:
        return ""
    word = match.group(0)
    return word[0].upper() + word[1:].lower()


# Hậu tố của số hiệu cho biết loại văn bản, dùng khi tên mô tả không ghi loại.
HAU_TO_LOAI = [
    ("TTLT", "Thông tư liên tịch"),
    ("NĐ", "Nghị định"),
    ("TT", "Thông tư"),
    ("QĐ", "Quyết định"),
    ("NQ", "Nghị quyết"),
    ("CT", "Chỉ thị"),
    ("QH", "Luật"),
]


def loai_tu_so(so):
    for suffix, loai in HAU_TO_LOAI:
        if re.search(rf"(?:^|[-/]){suffix}\d*(?:-|/|$)", so or ""):
            return loai
    return ""


# ----- Công báo điện tử Chính phủ -----

def parse_rss(xml_text):
    """Mỗi mục: tên văn bản nằm trong description (title để trống), link là trang chi tiết."""
    root = ET.fromstring(xml_text.encode("utf-8"))
    items = []
    for node in root.iter("item"):
        link = (node.findtext("link") or "").strip()
        ten = clean(node.findtext("description") or "")
        if not link or not ten:
            continue
        ngay = ""
        if node.findtext("pubDate"):
            ngay = email.utils.parsedate_to_datetime(node.findtext("pubDate")).date().isoformat()
        items.append({"url": link, "ten": ten, "ngay_ban_hanh": ngay})
    return items


def parse_chi_tiet_chinh_phu(page):
    """Số ký hiệu nằm trong JSON-LD (trường name); ngày ban hành và hiệu lực nằm trong phần thuộc tính."""
    so = ""
    match = re.search(r'"name"\s*:\s*"([^"]*\d{1,4}/\d{4}/[^"]*)"', page)
    if match:
        found = re.search(r"\d{1,4}/\d{4}/[^\s,;]+", clean(match.group(1)))
        so = found.group(0) if found else ""
    text = clean(page)
    ban_hanh = re.search(r"Ban hành:\s*(\d{2}/\d{2}/\d{4})", text)
    hieu_luc = re.search(r"Hiệu lực:\s*(\d{2}/\d{2}/\d{4})", text)
    return {
        "so_ky_hieu": so,
        "ngay_ban_hanh": iso_tu_ngay(ban_hanh.group(1)) if ban_hanh else "",
        "ngay_hieu_luc": iso_tu_ngay(hieu_luc.group(1)) if hieu_luc else "",
    }


CHINH_PHU_BASE = "https://congbao.chinhphu.vn"

# Các loại văn bản duyệt trên Công báo Chính phủ (mã loại lấy từ trang duyệt của cổng).
LOAI_DUYET = [
    "nghi-dinh-l1", "quyet-dinh-l2", "thong-tu-l3", "chi-thi-l4", "thong-tu-lien-tich-l5",
    "nghi-quyet-l6", "van-ban-hop-nhat-l7", "huong-dan-l21", "quy-dinh-l37", "luat-l13",
    "phap-lenh-l14", "lenh-l12", "nghi-quyet-lien-tich-l28", "thong-tu-lien-bo-l68",
]

# Lần nạp đầu duyệt từ ngày này trở đi (cùng phạm vi thời gian với vbpl.vn).
TU_NGAY_NAP_DAU = "2025-01-01"
TOI_DA_TRANG = 400

LISTING_ANCHOR = re.compile(r'<a\s[^>]*?href="(/van-ban/[^"]+\.htm)"([^>]*)>', re.S)


def parse_danh_sach_van_ban(page):
    """Trang duyệt theo loại: mỗi mục có liên kết (thuộc tính title là tên đầy đủ có số hiệu),
    và ngay sau đó là 'Ban hành', 'Hiệu lực' và 'Công báo số ... ngày ...'."""
    matches = list(LISTING_ANCHOR.finditer(page))
    items = []
    seen = set()
    for index, match in enumerate(matches):
        attrs = match.group(2)
        # Mỗi mục có liên kết tóm tắt (class="sapo"); dòng Ban hành/Hiệu lực nằm ngay sau liên kết này.
        title = re.search(r'title="([^"]*)"', attrs)
        if not title or 'class="sapo"' not in attrs:
            continue
        url = CHINH_PHU_BASE + match.group(1)
        if url in seen:
            continue
        seen.add(url)
        ten = clean(title.group(1))
        next_titled = [later.start() for later in matches[index + 1:] if 'class="sapo"' in later.group(2)]
        end = next_titled[0] if next_titled else len(page)
        text = clean(page[match.end():min(end, match.end() + 3000)])
        # Số hiệu đứng ngay sau chữ "số" (có thể không có năm, ví dụ "258/NQ-CP", "2109/QĐ-TTg").
        so = re.search(r"\bsố\s+(\d{1,5}/[^\s,;]+)", ten) or re.search(r"\d{1,4}/\d{4}/[^\s,;]+", ten)
        ban_hanh = re.search(r"Ban hành:\s*(\d{2}/\d{2}/\d{4})", text)
        hieu_luc = re.search(r"Hiệu lực:\s*(\d{2}/\d{2}/\d{4})", text)
        items.append({
            "url": url,
            "so_ky_hieu": so.group(1 if so.re.groups else 0) if so else "",
            "ten": ten,
            "trich_yeu": ten[so.end():].strip() if so else ten,
            "loai": loai_tu(ten),
            "ngay_ban_hanh": iso_tu_ngay(ban_hanh.group(1)) if ban_hanh else "",
            "ngay_hieu_luc": iso_tu_ngay(hieu_luc.group(1)) if hieu_luc else "",
        })
    return items


def duyet_cong_bao_chinh_phu(fetcher, keywords, tu_ngay=TU_NGAY_NAP_DAU, tu_den=None):
    """Duyệt mọi loại văn bản trong khoảng ngày [tu_ngay, tu_den] (tu_den là None thì không giới hạn trên).

    Trang duyệt xếp từ mới đến cũ, nên mỗi loại dừng khi cả trang chỉ còn văn bản cũ hơn tu_ngay.
    """
    tong = 0
    found = {}
    for loai in LOAI_DUYET:
        for trang in range(1, TOI_DA_TRANG + 1):
            if trang == 1:
                url = f"{CHINH_PHU_BASE}/van-ban-dang-cong-bao/{loai}.htm"
            else:
                url = f"{CHINH_PHU_BASE}/van-ban-dang-cong-bao/{loai}/trang-{trang}.htm"
            try:
                page = fetcher.get_text(url)
            except BlockedError:
                raise
            except RuntimeError:
                if trang == 1:
                    raise
                break
            items = parse_danh_sach_van_ban(page)
            if not items:
                break
            tong += len(items)
            co_ngay = [item for item in items if item["ngay_ban_hanh"]]
            if co_ngay and all(item["ngay_ban_hanh"] < tu_ngay for item in co_ngay):
                break
            for item in items:
                ngay = item["ngay_ban_hanh"]
                if ngay and ngay < tu_ngay:
                    continue
                if ngay and tu_den and ngay > tu_den:
                    continue
                found.setdefault(item["url"], item)
    kept = [item for item in found.values() if phu_hop_pham_vi(item["ten"], keywords, item["so_ky_hieu"])]
    return {"tong": tong, "items": kept}


def doc_chinh_phu(fetcher, keywords, known, toan_bo=False):
    """Lần nạp đầu duyệt toàn bộ loại văn bản từ 2025; các lần sau chỉ đọc RSS văn bản mới ban hành."""
    if toan_bo:
        return duyet_cong_bao_chinh_phu(fetcher, keywords)
    feed = parse_rss(fetcher.get_text(RSS_CHINH_PHU))
    items = []
    fetched = 0
    for entry in feed:
        if not phu_hop(entry["ten"], keywords):
            continue
        if entry["url"] in known:
            items.append(known[entry["url"]])
            continue
        if fetched >= MAX_CHI_TIET_MOI_LAN:
            continue
        fetched += 1
        try:
            detail = parse_chi_tiet_chinh_phu(fetcher.get_text(entry["url"]))
        except BlockedError:
            raise
        except RuntimeError:
            continue
        if not detail["so_ky_hieu"]:
            continue
        if not phu_hop_pham_vi(entry["ten"], keywords, detail["so_ky_hieu"]):
            continue
        items.append({
            "url": entry["url"],
            "so_ky_hieu": detail["so_ky_hieu"],
            "loai": loai_tu(entry["ten"]) or loai_tu_so(detail["so_ky_hieu"]),
            "trich_yeu": entry["ten"],
            "co_quan_ban_hanh": "",
            "ngay_ban_hanh": detail["ngay_ban_hanh"] or entry["ngay_ban_hanh"],
            "ngay_hieu_luc": detail["ngay_hieu_luc"],
        })
    return {"tong": len(feed), "items": items}


# ----- Công báo Thành phố Hồ Chí Minh -----

ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TPHCM_LINK = re.compile(r'<a href="(/cong-bao/van-ban/[^"]*/noi-dung/\d+(?:/\d+)?)"[^>]*>(.*?)</a>', re.S)
TPHCM_SO_LINK = re.compile(r'href="(/cong-bao/so/[^"]+)"')

# Số Công báo gần nhất được đọc mỗi lần chạy (mỗi số có thể chứa nhiều văn bản).
SO_CONG_BAO_GAN_NHAT = 8


def canonical_tphcm(href):
    """Cùng một văn bản có thể có hai dạng đường dẫn (…/noi-dung/ID và …/noi-dung/ID/SỐ): lấy dạng ngắn."""
    return re.sub(r"(noi-dung/\d+)/\d+$", r"\1", href)


def parse_cong_bao_tphcm(page):
    """Bảng 'Văn bản mới': ngày ban hành, trích yếu (kèm số hiệu trong thẻ span), ngày hiệu lực."""
    tong = 0
    items = []
    for row in ROW.findall(page):
        link = TPHCM_LINK.search(row)
        cells = CELL.findall(row)
        if not link or len(cells) < 3:
            continue
        tong += 1
        inner = re.split(r'<div class="doc_nav"', link.group(2))[0]
        span = re.search(r"<span>(.*?)</span>", inner, re.S)
        so_text = clean(span.group(1)) if span else ""
        so = re.search(r"\d{1,4}/\d{4}/\S+", so_text)
        if not so:
            continue
        bold = re.search(r"<b>(.*?)</b>", inner, re.S)
        co_quan = clean(bold.group(1)) if bold else ""
        text = clean(inner)
        trich = text.split(co_quan, 1)[-1].strip() if co_quan and co_quan in text else text[len(so_text):].strip()
        items.append({
            "url": CONG_BAO_TPHCM + canonical_tphcm(link.group(1)),
            "so_ky_hieu": so.group(0),
            "loai": so_text.split(" số")[0].strip(),
            "trich_yeu": trich,
            "co_quan_ban_hanh": co_quan,
            "ngay_ban_hanh": iso_tu_ngay(clean(cells[0])),
            "ngay_hieu_luc": iso_tu_ngay(clean(cells[2])),
        })
    return {"tong": tong, "items": items}


def parse_danh_sach_so(page):
    """Trang 'Công báo số': các số mới nhất đứng đầu."""
    issues = []
    for match in TPHCM_SO_LINK.finditer(page):
        if match.group(1) not in issues:
            issues.append(match.group(1))
    return issues


TIN_LINK = re.compile(r'<a href="(/tin-tuc-tong-hop/[^"]+)"[^>]*>(.*?)</a>', re.S)
LOAI_THEO_SO = re.compile(r"^(Quyết định|Nghị quyết|Chỉ thị|Thông tư|Nghị định|Công văn)\s+số", re.IGNORECASE)


def parse_trang_so(page, duong_dan_so=""):
    """Trang một số Công báo.

    - Văn bản có trang nội dung (…/noi-dung/ID): số hiệu nằm trong liên kết, ngày nằm trong đường dẫn.
    - Thông báo công bố trong dải tin của số (…/tin-tuc-tong-hop/…): số hiệu nằm trong tiêu đề tin,
      ngày lấy theo ngày của số Công báo (ngày đăng, không phải ngày ban hành).
    """
    items = []
    for match in TPHCM_LINK.finditer(page):
        href = match.group(1)
        text = clean(re.split(r'<div class="doc_nav"', match.group(2))[0])
        so = re.search(r"\d{1,4}/\d{4}/\S+", text)
        if not so:
            continue
        ngay = re.search(r"/ngay/(\d{2}-\d{2}-\d{4})/", href)
        items.append({
            "url": CONG_BAO_TPHCM + canonical_tphcm(href),
            "so_ky_hieu": so.group(0),
            "loai": re.sub(r"\s*số\s*$", "", text[:so.start()]).strip(),
            "trich_yeu": text[so.end():].strip(),
            "co_quan_ban_hanh": "",
            "ngay_ban_hanh": iso_tu_ngay(ngay.group(1)) if ngay else "",
            "ngay_hieu_luc": "",
        })
    ngay_so = re.search(r"(\d{2}-\d{2}-\d{4})$", duong_dan_so or "")
    for match in TIN_LINK.finditer(page):
        text = clean(match.group(2))
        loai = LOAI_THEO_SO.match(text)
        # Số hiệu của quyết định công bố TTHC có dạng "6676/QĐ-UBND" (không có năm), nên đọc theo chữ "số".
        so = re.search(r"\bsố\s+([0-9][^\s,;]*)", text)
        if not so or not loai:
            continue
        items.append({
            "url": CONG_BAO_TPHCM + match.group(1),
            "so_ky_hieu": so.group(1),
            "loai": loai.group(1)[0].upper() + loai.group(1)[1:].lower(),
            "trich_yeu": text[so.end():].strip(),
            "co_quan_ban_hanh": "",
            "ngay_ban_hanh": iso_tu_ngay(ngay_so.group(1)) if ngay_so else "",
            "ngay_hieu_luc": "",
        })
    return items


def doc_tphcm(fetcher, keywords, known, toan_bo=False):
    """Bảng 'Văn bản mới' cộng các số Công báo, khử trùng theo đường dẫn văn bản.

    Lần nạp đầu đọc mọi số Công báo đang được liệt kê; các lần sau chỉ đọc vài số gần nhất.
    """
    found = {}
    parsed = parse_cong_bao_tphcm(fetcher.get_text(CONG_BAO_TPHCM_VAN_BAN_MOI))
    tong = parsed["tong"]
    for item in parsed["items"]:
        found.setdefault(item["url"], item)
    issues = parse_danh_sach_so(fetcher.get_text(CONG_BAO_TPHCM + "/cong-bao/so"))
    if not toan_bo:
        issues = issues[:SO_CONG_BAO_GAN_NHAT]
    for path in issues:
        for item in parse_trang_so(fetcher.get_text(CONG_BAO_TPHCM + path), path):
            tong += 1
            found.setdefault(item["url"], item)
    items = [
        item for item in found.values()
        if phu_hop_pham_vi(f"{item['so_ky_hieu']} {item['trich_yeu']}", keywords, item["so_ky_hieu"],
                           item["co_quan_ban_hanh"])
    ]
    return {"tong": tong, "items": items}


# ----- Cổng Bộ Công an (trang chủ, các thẻ văn bản) -----

CARD = re.compile(r'<a\s[^>]*?href="(/co-so-du-lieu-van-ban/[^"?]+)\?tab=fulltext"')


def parse_bo_cong_an(page):
    """Mỗi thẻ: liên kết số hiệu (có thẻ p), liên kết tên văn bản, rồi cơ quan và các ngày."""
    starts = {}
    for match in CARD.finditer(page):
        starts.setdefault(match.group(1), match.start())
    order = sorted(starts.items(), key=lambda pair: pair[1])
    items = []
    for index, (path, start) in enumerate(order):
        end = order[index + 1][1] if index + 1 < len(order) else len(page)
        segment = page[start:min(end, start + 3000)]
        anchors = re.findall(rf'<a href="{re.escape(path)}\?tab=fulltext"[^>]*>(.*?)</a>', segment, re.S)
        number_anchor = next((anchor for anchor in anchors if "<p" in anchor), None)
        title_anchor = next((anchor for anchor in anchors if "<p" not in anchor), None)
        if not number_anchor or not title_anchor:
            continue
        number_text = clean(number_anchor)
        so = re.search(r"\d{1,4}/\d{4}/\S+", number_text)
        if not so:
            continue
        text = clean(segment)
        co_quan = re.search(r"Cơ quan ban hành:\s*(.+?)\s+Ngày ban hành", text)
        ban_hanh = re.search(r"Ngày ban hành:\s*(\d{2}/\d{2}/\d{4})", text)
        hieu_luc = re.search(r"Ngày hiệu lực:\s*(\d{2}/\d{2}/\d{4})", text)
        items.append({
            "url": BO_CONG_AN + path,
            "so_ky_hieu": so.group(0),
            "loai": re.sub(r"^\d+\s*", "", number_text).split(so.group(0))[0].strip(),
            "trich_yeu": clean(title_anchor),
            "co_quan_ban_hanh": co_quan.group(1).strip() if co_quan else "",
            "ngay_ban_hanh": iso_tu_ngay(ban_hanh.group(1)) if ban_hanh else "",
            "ngay_hieu_luc": iso_tu_ngay(hieu_luc.group(1)) if hieu_luc else "",
        })
    return {"tong": len(order), "items": items}


def doc_bo_cong_an(fetcher, keywords, known, toan_bo=False):
    # Cổng chỉ công khai các văn bản mới trên trang chủ; lịch sử đầy đủ nằm sau lớp bảo vệ, không đọc ở đây.
    parsed = parse_bo_cong_an(fetcher.get_text(BO_CONG_AN + "/"))
    items = [
        item for item in parsed["items"]
        if phu_hop_pham_vi(item["trich_yeu"], keywords, item["so_ky_hieu"], item["co_quan_ban_hanh"])
    ]
    return {"tong": parsed["tong"], "items": items}


# Thứ tự đọc các nguồn.
READERS = {
    "chinh_phu": doc_chinh_phu,
    "tphcm": doc_tphcm,
    "bo_cong_an": doc_bo_cong_an,
}


def tu_khoa_giai_doan(giai_doan, tu_khoa_vbpl=()):
    """Từ khóa theo giai đoạn: giai đoạn 1 là thủ tục và cư trú; giai đoạn 2 thêm các lĩnh vực
    đã thống nhất trong vbpl_config.json (ANTT, vũ khí, con dấu, khu phố, hộ tịch...);
    giai đoạn 3 thêm đăng ký khác với công an (mới sinh con, đăng ký xe, PCCC, xuất nhập cảnh)."""
    if giai_doan == 1:
        return list(GIAI_DOAN_1)
    if giai_doan == 2:
        return list(dict.fromkeys(list(GIAI_DOAN_1) + list(tu_khoa_vbpl)))
    return list(dict.fromkeys(list(GIAI_DOAN_1) + list(tu_khoa_vbpl) + GIAI_DOAN_3))


def khoa_nen(nguon, giai_doan):
    """Khóa đánh dấu lần nạp đầu của một nguồn trong một giai đoạn (lần nạp đầu không báo văn bản mới)."""
    return f"chinh_thuc_nen:{nguon}:{giai_doan}"
