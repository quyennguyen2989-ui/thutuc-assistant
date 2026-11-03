"""Đồng bộ văn bản từ vbpl.vn vào cơ sở dữ liệu.

Hai việc, chạy khác tần suất:
- Tìm văn bản (đọc toàn bộ sitemap, khoảng 36 tệp): mỗi tuần một lần, hoặc khi thiếu văn bản đang theo dõi.
  Tìm theo số ký hiệu của văn bản đang theo dõi và theo từ khóa (văn bản mới).
- Đọc trạng thái (mở từng trang chi tiết): mỗi ngày, cho mọi văn bản đã biết.
"""

import json
import zlib
from datetime import date, timedelta
from pathlib import Path

from . import store, vbpl

CONFIG_PATH = Path(__file__).resolve().parent / "vbpl_config.json"
DISCOVERY_STATE = "vbpl_kham_pha_luc"
SEARCHED_STATE = "vbpl_so_da_tim"


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


NAM_BAT_DAU_LICH_SU = 2025  # văn bản từ năm này trở đi là phạm vi nạp chính; trước đó chỉ lấy khi cần


def _van_ban_thay_the(conn):
    """Số ký hiệu từ 2025 trở đi nằm trong lịch sử sửa đổi, bổ sung, thay thế của văn bản cũ đã hết hiệu lực.

    Đây là các văn bản mới cần tìm để thay cho văn bản cũ, kể cả khi văn bản cũ không còn được đưa vào dữ liệu.
    """
    numbers = set()
    for row in store.load_vbpl(conn):
        if not row["lich_su"] or not (row["tinh_trang"] or "").startswith("Hết hiệu lực"):
            continue
        for item in json.loads(row["lich_su"]):
            for found in vbpl.NUMBER_IN_TEXT.findall(item.get("van_ban_nguon") or ""):
                if int(found.split("/")[1]) >= NAM_BAT_DAU_LICH_SU:
                    numbers.add(found)
    return numbers


def watched_numbers(conn, extra_numbers):
    """Số ký hiệu cần theo dõi: văn bản của cổng, văn bản bổ sung, căn cứ của các thủ tục,
    và văn bản mới thay thế các văn bản cũ đã hết hiệu lực."""
    numbers = set(extra_numbers) | _van_ban_thay_the(conn)
    for record in store.load_records(conn, "van_ban"):
        if record["so_ky_hieu"]:
            numbers.add(record["so_ky_hieu"])
    # Căn cứ của thủ tục từ cổng TP.HCM và từ cổng quốc gia (phần công an) đều cần trạng thái vbpl.
    for procedure in store.load_records(conn, "tthc") + store.load_records(conn, "tthc_qg"):
        for title in procedure["can_cu"]:
            numbers.update(vbpl.NUMBER_IN_TEXT.findall(title))
    return sorted(numbers)


def discovery_due(conn, run_date, interval_days):
    last = store.get_state(conn, DISCOVERY_STATE)
    if not last:
        return True
    return date.fromisoformat(last) + timedelta(days=interval_days) <= run_date


def discover(conn, numbers, config, run_date, delay):
    """Đọc toàn bộ sitemap, ghi nhận văn bản theo số ký hiệu và văn bản mới theo từ khóa."""
    entries = []
    for sheet in list(vbpl.CENTRAL_SHEETS) + list(vbpl.LOCAL_SHEETS):
        xml = vbpl.fetch_text(f"{vbpl.SITE}/sitemap/{sheet}.xml", delay)
        entries.extend(vbpl.read_urlset(xml, sheet))

    matched = 0
    for number in numbers:
        hit = vbpl.find_by_number(entries, number)
        if hit:
            store.upsert_vbpl(conn, {
                "url": hit["url"], "so_ky_hieu": number, "sheet": hit["sheet"], "lastmod": hit["lastmod"],
            })
            matched += 1

    known = {row["url"] for row in store.load_vbpl(conn)}
    new_found = 0
    for hit in vbpl.discover(entries, config["tu_khoa_tim_van_ban_moi"], config["tu_ngay_tim_van_ban_moi"]):
        if hit["url"] not in known:
            store.upsert_vbpl(conn, {
                "url": hit["url"], "sheet": hit["sheet"], "lastmod": hit["lastmod"],
            })
            new_found += 1

    store.set_state(conn, DISCOVERY_STATE, run_date.isoformat())
    return {"so_sanh_duoc": len(entries), "theo_so_ky_hieu": matched, "van_ban_moi": new_found}


def read_statuses(conn, run_at, delay, keywords, only_urls=None):
    """Mở trang chi tiết của văn bản đang theo dõi, lưu tình trạng và ghi nhận thay đổi.

    only_urls: nếu có, chỉ đọc các đường dẫn này (dùng khi vừa tìm được văn bản mới).
    """
    rows = store.load_vbpl(conn)
    by_url = {row["url"]: row for row in rows}
    targets = [
        row["url"] for row in rows
        if (row["so_ky_hieu"] or vbpl.is_relevant(row["url"], row["sheet"], keywords))
        and (only_urls is None or row["url"] in only_urls)
    ]
    # Văn bản đang theo dõi (căn cứ của thủ tục, văn bản của cổng) có thêm mục lịch sử sửa đổi.
    history_urls = frozenset(row["url"] for row in rows if row["so_ky_hieu"])
    # Lần đầu có trạng thái thì chỉ ghi nhận nền, không báo thay đổi.
    baseline = not any(row["tinh_trang"] for row in rows)

    def save(url, info):
        if info.get("loi"):
            store.upsert_vbpl(conn, {"url": url, "kiem_tra_luc": run_at, "loi": info["loi"]})
            return
        new = {
            "tieu_de": info.get("tieu_de"),
            "tinh_trang": info.get("tinh_trang"),
            "ngay_hieu_luc": info.get("ngay_hieu_luc"),
            "ngay_cap_nhat": info.get("ngay_cap_nhat"),
        }
        if info.get("lich_su") is not None:
            new["lich_su"] = json.dumps(info["lich_su"], ensure_ascii=False)
        store.upsert_vbpl(conn, {"url": url, **new, "kiem_tra_luc": run_at, "loi": None})
        if not baseline and new["tinh_trang"]:
            _record_change(conn, run_at, url, by_url.get(url, {}), new)

    vbpl.read_detail_pages(targets, save, delay_seconds=delay, history_urls=history_urls)
    return len(targets)


def _record_change(conn, run_at, url, old, new):
    """Ghi nhận văn bản mới có trạng thái, hoặc văn bản đã đổi tình trạng/ngày."""
    name = new["tieu_de"] or url
    record_id = zlib.crc32(url.encode("utf-8"))
    if not old.get("tinh_trang"):
        store.record_change(conn, run_at, "vbpl", record_id, "moi", {
            "_ten": name, "tinh_trang": {"cu": None, "moi": new["tinh_trang"]},
        })
        return
    diff = {
        field: {"cu": old.get(field), "moi": new[field]}
        for field in ("tinh_trang", "ngay_hieu_luc", "ngay_cap_nhat")
        if old.get(field) != new[field]
    }
    # Thêm lần sửa đổi, bổ sung mới trong lịch sử cũng là một thay đổi cần báo.
    if new.get("lich_su") is not None and old.get("lich_su") != new["lich_su"]:
        diff["lich_su"] = {
            "cu": _count_history(old.get("lich_su")),
            "moi": _count_history(new["lich_su"]),
        }
    if diff:
        diff["_ten"] = name
        store.record_change(conn, run_at, "vbpl", record_id, "thay_doi", diff)


def _count_history(raw):
    """Số mục lịch sử đã lưu (chuỗi JSON hoặc danh sách)."""
    if not raw:
        return 0
    return len(json.loads(raw)) if isinstance(raw, str) else len(raw)


def sync(conn, extra_numbers, run_at, run_date, config):
    """Chạy đồng bộ vbpl.vn. Trả về số văn bản đã đọc trạng thái."""
    delay = config["do_tre_giua_cac_yeu_cau_giay"]
    numbers = watched_numbers(conn, extra_numbers)
    searched = set(json.loads(store.get_state(conn, SEARCHED_STATE, "[]")))
    new_numbers = [number for number in numbers if number not in searched]

    full = bool(new_numbers) or discovery_due(conn, run_date, config["chu_ky_tim_van_ban_moi_ngay"])
    if full:
        summary = discover(conn, numbers, config, run_date, delay)
        store.set_state(conn, SEARCHED_STATE, json.dumps(numbers, ensure_ascii=False))
        print(f"vbpl.vn: đã tìm văn bản — {summary}")

    # Lần đầu và mỗi chu kỳ tìm kiếm thì đọc lại toàn bộ tình trạng (đối chiếu đầy đủ).
    # Các lần khác chỉ đọc văn bản chưa từng kiểm tra, đang lỗi, hoặc có ngày sửa trên sơ đồ trang
    # mới hơn lần kiểm tra gần nhất, để việc cập nhật hằng ngày nhẹ hơn.
    only_urls = None if full else _can_kiem_tra_lai(conn)
    return read_statuses(conn, run_at, delay, config["tu_khoa_tim_van_ban_moi"], only_urls=only_urls)


def _can_kiem_tra_lai(conn):
    """Đường dẫn các văn bản cần đọc lại trạng thái trong lần chạy gia tăng."""
    urls = set()
    for row in store.load_vbpl(conn):
        if row["loi"] or not row["kiem_tra_luc"]:
            urls.add(row["url"])
        elif row["lastmod"] and row["lastmod"][:10] > row["kiem_tra_luc"][:10]:
            urls.add(row["url"])
    return urls
