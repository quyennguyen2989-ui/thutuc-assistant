"""Tìm văn bản mới trên vbpl.vn, chạy độc lập và không cần cơ sở dữ liệu. Dùng trên máy chủ server-chat.

Lý do: GitHub Actions bị vbpl.vn chặn (sơ đồ trang trả 403), còn server-chat đọc được. Mô-đun này chỉ dùng
thư viện chuẩn của Python. Logic khớp với vbpl_sync.discover: tìm theo số ký hiệu cần theo dõi và theo từ khóa.

Cách chạy, từ thư mục chứa gói crawler:
    python -m crawler.kham_pha_vbpl --van-ban van_ban.json --tthc tthc.json --dau-ra vbpl_kham_pha.json

Mã thoát: 0 xong; 1 lỗi không mong đợi; 2 vbpl.vn chặn. Khi lỗi, tệp đầu ra không được ghi đè,
nên tệp cũ vẫn còn và bước đọc của CI biết là kết quả đã cũ.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import kham_pha_github, vbpl
from .client import BlockedError

CONFIG_PATH = Path(__file__).resolve().parent / "vbpl_config.json"
GIO_VIET_NAM = timezone(timedelta(hours=7))
SO_LAN_THU_TAI_SO_DO = 3
NGHI_GIUA_CAC_LAN_THU_GIAY = 10


def load_config(path=CONFIG_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _doc_danh_sach(path):
    """Tệp JSON dạng danh sách, hoặc dạng {"items": [...]}."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("items", [])


def so_ky_hieu_can_theo_doi(van_ban_items, tthc_items):
    """Số ký hiệu cần tìm trên vbpl.vn: số của văn bản đã có và số trong phần căn cứ của thủ tục."""
    numbers = set()
    for item in van_ban_items:
        if item.get("so_ky_hieu"):
            numbers.add(item["so_ky_hieu"])
    for item in tthc_items:
        for title in item.get("can_cu") or []:
            numbers.update(vbpl.NUMBER_IN_TEXT.findall(title))
    return sorted(numbers)


def tim_van_ban(entries, numbers, keywords, cutoff):
    """Văn bản khớp một số ký hiệu cần theo dõi hoặc một từ khóa mới. Mỗi đường dẫn một dòng, sắp theo đường dẫn."""
    found = {}

    def ghi(entry, so_ky_hieu=None, theo_tu_khoa=False):
        row = found.setdefault(entry["url"], {
            "url": entry["url"],
            "sheet": entry["sheet"],
            "lastmod": entry["lastmod"],
            "so_ky_hieu": None,
            "theo_tu_khoa": False,
        })
        if so_ky_hieu and not row["so_ky_hieu"]:
            row["so_ky_hieu"] = so_ky_hieu
        row["theo_tu_khoa"] = row["theo_tu_khoa"] or theo_tu_khoa

    # Sơ đồ có hàng trăm nghìn đường dẫn. Chỉ xét đường dẫn có chứa chuỗi số trong tên (nhanh hơn nhiều
    # so với quét toàn bộ cho từng số); kết quả vẫn do vbpl.find_by_number quyết định.
    slugs = [vbpl.slug_of(entry["url"]) for entry in entries]
    for number in numbers:
        needle = vbpl.normalize_number(number)
        candidates = [entry for entry, slug in zip(entries, slugs) if needle in slug]
        hit = vbpl.find_by_number(candidates, number) if candidates else None
        if hit:
            ghi(hit, so_ky_hieu=number)
    for hit in vbpl.discover(entries, keywords, cutoff):
        ghi(hit, theo_tu_khoa=True)
    return [found[url] for url in sorted(found)]


def _tai_so_do_mot_tep(sheet, delay, lan_thu=SO_LAN_THU_TAI_SO_DO, nghi_giay=NGHI_GIUA_CAC_LAN_THU_GIAY):
    """Tải một tệp sơ đồ. Thử lại khi lỗi tạm thời (kết nối đóng, HTTP 5xx). Bị chặn thì dừng ngay."""
    for lan in range(1, lan_thu + 1):
        try:
            return vbpl.fetch_text(f"{vbpl.SITE}/sitemap/{sheet}.xml", delay)
        except BlockedError:
            raise
        except OSError as error:  # URLError và HTTPError đều là OSError
            if lan == lan_thu:
                raise
            print(f"sơ đồ {sheet}: lỗi tạm thời ({error}), thử lại sau {nghi_giay} giây", file=sys.stderr)
            time.sleep(nghi_giay)


def tai_so_do(delay):
    """Đọc toàn bộ tệp sơ đồ của vbpl.vn. Một tệp không tải được thì ném lỗi, để không bỏ sót văn bản."""
    entries = []
    for sheet in list(vbpl.CENTRAL_SHEETS) + list(vbpl.LOCAL_SHEETS):
        xml = _tai_so_do_mot_tep(sheet, delay)
        moi = vbpl.read_urlset(xml, sheet)
        entries.extend(moi)
        print(f"sơ đồ {sheet}: {len(moi)} đường dẫn", file=sys.stderr, flush=True)
    return entries


def _ghi_tep_an_toan(duong_dan, noi_dung):
    """Ghi qua tệp tạm rồi đổi tên, để không bao giờ có tệp ghi dở."""
    dich = Path(duong_dan)
    tam = dich.with_name(dich.name + ".tam")
    tam.write_text(noi_dung, encoding="utf-8")
    tam.replace(dich)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tìm văn bản mới trên vbpl.vn cho bước đọc của CI.")
    parser.add_argument("--van-ban", required=True, help="docs/data/van_ban.json")
    parser.add_argument("--tthc", required=True, help="docs/data/tthc.json")
    parser.add_argument("--dau-ra", required=True, help="tệp JSON kết quả")
    parser.add_argument("--cau-hinh", default=str(CONFIG_PATH), help="vbpl_config.json")
    parser.add_argument("--day-github", help="tệp chứa token GitHub; nếu có thì đẩy kết quả lên repo")
    args = parser.parse_args(argv)

    config = load_config(args.cau_hinh)
    numbers = so_ky_hieu_can_theo_doi(_doc_danh_sach(args.van_ban), _doc_danh_sach(args.tthc))
    try:
        entries = tai_so_do(config["do_tre_giua_cac_yeu_cau_giay"])
    except BlockedError as error:
        print(f"vbpl.vn chặn: {error}. Giữ kết quả cũ.", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"Không tải được sơ đồ vbpl.vn: {error}. Giữ kết quả cũ.", file=sys.stderr)
        return 1

    van_ban = tim_van_ban(entries, numbers, config["tu_khoa_tim_van_ban_moi"], config["tu_ngay_tim_van_ban_moi"])
    ket_qua = {
        "tao_luc": datetime.now(GIO_VIET_NAM).isoformat(timespec="seconds"),
        "so_sanh_duoc": len(entries),
        "so_ky_hieu_da_tim": len(numbers),
        "van_ban": van_ban,
    }
    noi_dung = json.dumps(ket_qua, ensure_ascii=False, indent=1)
    _ghi_tep_an_toan(args.dau_ra, noi_dung)
    print(f"vbpl.vn: so sánh {len(entries)} đường dẫn, {len(numbers)} số ký hiệu, khớp {len(van_ban)} văn bản.")

    if args.day_github:
        thong_diep = f"Cập nhật tìm văn bản vbpl trên server-chat ({ket_qua['tao_luc'][:10]})"
        try:
            token = kham_pha_github.doc_token(args.day_github)
            da_day = kham_pha_github.day_tep(token, noi_dung.encode("utf-8"), thong_diep)
        except (kham_pha_github.LoiGitHub, OSError) as error:
            print(f"Không đẩy được lên GitHub: {error}. Tệp trên máy chủ vẫn được giữ.", file=sys.stderr)
            return 1
        print("vbpl.vn: đã đẩy lên GitHub." if da_day else "vbpl.vn: nội dung không đổi, không đẩy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
