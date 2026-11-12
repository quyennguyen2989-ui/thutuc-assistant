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
from .client import BlockedError

CONFIG_PATH = Path(__file__).resolve().parent / "vbpl_config.json"
DISCOVERY_STATE = "vbpl_kham_pha_luc"
SEARCHED_STATE = "vbpl_so_da_tim"
DOC_DAY_DU_STATE = "vbpl_doc_day_du_luc"  # ngày đọc lại toàn bộ tình trạng gần nhất


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

    known = {row["url"] for row in store.load_vbpl(conn)}
    url_moi = set()  # đường dẫn chưa từng có trong dữ liệu: cần đọc ngay trong lần chạy này
    matched = 0
    for number in numbers:
        hit = vbpl.find_by_number(entries, number)
        if hit:
            if hit["url"] not in known:
                url_moi.add(hit["url"])
            store.upsert_vbpl(conn, {
                "url": hit["url"], "so_ky_hieu": number, "sheet": hit["sheet"], "lastmod": hit["lastmod"],
            })
            matched += 1

    new_found = 0
    for hit in vbpl.discover(entries, config["tu_khoa_tim_van_ban_moi"], config["tu_ngay_tim_van_ban_moi"]):
        if hit["url"] not in known:
            store.upsert_vbpl(conn, {
                "url": hit["url"], "sheet": hit["sheet"], "lastmod": hit["lastmod"],
            })
            url_moi.add(hit["url"])
            new_found += 1

    store.set_state(conn, DISCOVERY_STATE, run_date.isoformat())
    return {
        "so_sanh_duoc": len(entries), "theo_so_ky_hieu": matched, "van_ban_moi": new_found,
        "url_moi": sorted(url_moi),
    }


def _can_doc_day_du(conn, run_date, chu_ky_ngay):
    """Đến kỳ đọc lại toàn bộ tình trạng (mặc định mỗi 7 ngày). Việc phát hiện văn bản mới vẫn chạy mỗi ngày."""
    last = store.get_state(conn, DOC_DAY_DU_STATE)
    if not last:
        return True
    return date.fromisoformat(last) + timedelta(days=chu_ky_ngay) <= run_date


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
    so_loi = 0
    so_khong_con = 0

    def save(url, info):
        nonlocal so_loi, so_khong_con
        if info.get("khong_con"):
            # Liên kết không còn trên vbpl.vn: giữ trạng thái đã biết, không tính là lỗi tạm thời.
            so_khong_con += 1
            store.upsert_vbpl(conn, {"url": url, "kiem_tra_luc": run_at, "loi": info["loi"]})
            return
        if info.get("loi"):
            so_loi += 1
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
    return len(targets), so_loi, so_khong_con


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


KET_QUA_SERVER = Path(__file__).resolve().parents[1] / "data" / "vbpl_kham_pha.json"
SO_NGAY_KET_QUA_SERVER_CON_HAN = 1


def doc_ket_qua_server(run_date, path=KET_QUA_SERVER):
    """Danh sách văn bản do server-chat tìm được, hoặc None nếu thiếu, đã cũ hoặc mới hơn ngày chạy.

    Chỉ nhận kết quả của hôm nay hoặc tối đa một ngày trước. server-chat tìm văn bản mới hằng ngày,
    vì GitHub Actions bị vbpl.vn chặn sơ đồ trang.
    """
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    tao = date.fromisoformat(data["tao_luc"][:10])
    if not run_date - timedelta(days=SO_NGAY_KET_QUA_SERVER_CON_HAN) <= tao <= run_date:
        return None
    return data.get("van_ban", [])


def nap_ket_qua_server(conn, van_ban, run_date):
    """Ghi văn bản server-chat tìm được vào dữ liệu. Trả về các đường dẫn chưa từng có (cần đọc ngay).

    Chỉ ghi trường có giá trị: trường thiếu giữ nguyên, nên không xóa số ký hiệu đã biết.
    """
    known = {row["url"] for row in store.load_vbpl(conn)}
    url_moi = set()
    for item in van_ban:
        url = item["url"]
        if url not in known:
            url_moi.add(url)
        row = {"url": url}
        for field in ("so_ky_hieu", "sheet", "lastmod"):
            if item.get(field) not in (None, ""):
                row[field] = item[field]
        store.upsert_vbpl(conn, row)
    store.set_state(conn, DISCOVERY_STATE, run_date.isoformat())
    return url_moi


def sync(conn, extra_numbers, run_at, run_date, config):
    """Chạy đồng bộ vbpl.vn. Trả về (số văn bản đã đọc trạng thái, số văn bản đọc lỗi, lỗi khi tìm văn bản hoặc None).

    Lỗi khi tìm văn bản (đọc sitemap) không chặn việc đọc trạng thái các văn bản đã theo dõi: trước đây
    lỗi ở bước này làm bỏ qua cả việc đọc trạng thái, nên không có văn bản nào được cập nhật.
    Bị chặn (BlockedError) thì dừng hẳn, không đọc tiếp.
    """
    delay = config["do_tre_giua_cac_yeu_cau_giay"]
    numbers = watched_numbers(conn, extra_numbers)
    searched = set(json.loads(store.get_state(conn, SEARCHED_STATE, "[]")))
    new_numbers = [number for number in numbers if number not in searched]

    # Phát hiện văn bản mới mỗi ngày (sơ đồ trang, khoảng vài phút), để văn bản mới được đọc ngay trong ngày.
    # Nếu server-chat đã tìm hôm nay thì không thử lại ở đây (sơ đồ trang bị GitHub chặn, thử chỉ tốn thời gian).
    ket_qua_server = doc_ket_qua_server(run_date)
    if ket_qua_server is None:
        tim_hom_nay = bool(new_numbers) or discovery_due(conn, run_date, config["chu_ky_tim_van_ban_moi_ngay"])
    else:
        tim_hom_nay = False
    loi_tim = None
    url_moi = set()
    if tim_hom_nay:
        try:
            summary = discover(conn, numbers, config, run_date, delay)
            url_moi = set(summary.pop("url_moi"))
            store.set_state(conn, SEARCHED_STATE, json.dumps(numbers, ensure_ascii=False))
            print(f"vbpl.vn: đã tìm văn bản — {summary}; văn bản mới cần đọc: {len(url_moi)}")
        except BlockedError as error:
            # Sơ đồ trang bị chặn: không đọc tiếp việc tìm văn bản, nhưng vẫn đọc trạng thái các văn bản đã theo dõi
            # (đọc trang chi tiết không bị chặn). Trước đây lỗi này dừng cả đợt đọc, nên tình trạng không được cập nhật.
            loi_tim = f"bị chặn khi tìm văn bản mới ({error})"
            print(f"vbpl.vn: {loi_tim}. Vẫn đọc trạng thái văn bản đã theo dõi.")
        except Exception as error:  # noqa: BLE001 - lỗi tìm văn bản không chặn việc đọc trạng thái
            loi_tim = str(error)
            print(f"vbpl.vn: lỗi khi tìm văn bản ({error}). Vẫn đọc trạng thái văn bản đã theo dõi.")

    if ket_qua_server is not None:
        url_moi = nap_ket_qua_server(conn, ket_qua_server, run_date)
        print(f"vbpl.vn: nạp {len(ket_qua_server)} văn bản do server-chat tìm; văn bản mới cần đọc: {len(url_moi)}")

    # Đọc lại toàn bộ tình trạng mỗi chu kỳ (mặc định 7 ngày) để đối chiếu đầy đủ. Các ngày khác chỉ đọc:
    # văn bản chưa từng kiểm tra, đang lỗi, có ngày sửa mới hơn lần kiểm tra, và văn bản mới vừa phát hiện.
    doc_day_du = loi_tim is None and _can_doc_day_du(conn, run_date, config.get("chu_ky_doc_day_du_ngay", 7))
    only_urls = None if doc_day_du else (_can_kiem_tra_lai(conn) | url_moi)
    so_doc, so_loi, so_khong_con = read_statuses(
        conn, run_at, delay, config["tu_khoa_tim_van_ban_moi"], only_urls=only_urls
    )
    if doc_day_du:
        store.set_state(conn, DOC_DAY_DU_STATE, run_date.isoformat())
    return so_doc, so_loi, loi_tim, so_khong_con


def _can_kiem_tra_lai(conn):
    """Đường dẫn các văn bản cần đọc lại trạng thái trong lần chạy gia tăng.

    Liên kết đã xác định là không còn trên vbpl.vn không đọc lại mỗi ngày (chỉ đọc trong đợt đối chiếu đầy đủ).
    """
    urls = set()
    for row in store.load_vbpl(conn):
        if vbpl.la_khong_con(row["loi"]):
            continue
        if row["loi"] or not row["kiem_tra_luc"]:
            urls.add(row["url"])
        elif row["lastmod"] and row["lastmod"][:10] > row["kiem_tra_luc"][:10]:
            urls.add(row["url"])
    return urls
