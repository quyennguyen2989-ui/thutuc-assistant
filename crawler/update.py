"""Điểm vào chính: python -m crawler.update

Tải dữ liệu từ cổng, so với lần chạy trước, ghi nhận thay đổi, rồi xuất JSON cho trang web.

Mã thoát:
  0  thành công
  1  lỗi (mạng, dữ liệu bất thường) — không ghi gì vào DB
  2  máy chủ từ chối truy cập (403/401/429) — dừng ngay, không thử lại
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from . import cong_dvc, export, normalize, nguon_chinh_thuc, nguon_text, sources, store, vbpl_sync, vbpl_text
from .client import BlockedError, PortalClient

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "thutuc.db"
RAW_DIR = ROOT / "data" / "raw"
DOCS_DATA_DIR = ROOT / "docs" / "data"
OVERRIDES_PATH = ROOT / "crawler" / "tinh_trang_thu_cong.json"
EXTRA_PATH = ROOT / "crawler" / "van_ban_bo_sung.json"

# Nếu số bản ghi giảm quá nửa so với lần trước, coi là cổng lỗi và không ghi gì.
MIN_RATIO = 0.5


def run():
    run_at = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = store.connect(DB_PATH)
    client = PortalClient()

    try:
        raw_van_ban = sources.fetch_van_ban(client)
        raw_tthc = []
        for item in sources.fetch_tthc_list(client):
            raw_tthc.append((item, sources.fetch_tthc_detail(client, item["ID"])))
    except BlockedError as error:
        _record_failure(conn, run_at, f"bi_chan: {error}")
        print(f"DỪNG: {error}. Không thử lại để tránh bị chặn thêm.")
        return 2
    except Exception as error:  # noqa: BLE001 - ghi nhận mọi lỗi mạng/dữ liệu rồi thoát
        _record_failure(conn, run_at, f"loi: {error}")
        print(f"LỖI: {error}")
        return 1

    van_ban = [normalize.normalize_van_ban(raw) for raw in raw_van_ban]
    tthc = [normalize.normalize_tthc(item, detail) for item, detail in raw_tthc]

    _save_raw_snapshot(run_at, raw_van_ban, raw_tthc)

    try:
        _check_sanity(conn, "van_ban", len(van_ban))
        _check_sanity(conn, "tthc", len(tthc))
    except RuntimeError as error:
        _record_failure(conn, run_at, f"bat_thuong: {error}")
        print(f"BẤT THƯỜNG: {error}. Không ghi dữ liệu.")
        return 1

    with conn:
        first_run = store.is_first_run(conn)
        change_count = store.sync_records(conn, "van_ban", van_ban, run_at, first_run)
        change_count += store.sync_records(conn, "tthc", tthc, run_at, first_run)
        store.log_run(conn, run_at, "ok", len(van_ban), len(tthc), change_count)

    if "--khong-chinh-thuc" not in sys.argv:
        for giai_doan in _cac_giai_doan():
            _sync_chinh_thuc(conn, run_at, giai_doan)
        _sync_nguon_text(conn)
    if "--khong-cong-dvc" not in sys.argv:
        _sync_cong_dvc(conn, run_at)
    if "--khong-vbpl" not in sys.argv:
        _sync_vbpl(conn, run_at)
    export.write_outputs(conn, DOCS_DATA_DIR, OVERRIDES_PATH, EXTRA_PATH, run_at)

    label = "lần đầu, ghi nhận nền" if first_run else f"{change_count} thay đổi"
    print(f"Xong. Văn bản: {len(van_ban)}, thủ tục: {len(tthc)}. {label}.")
    return 0


def _cac_giai_doan():
    """Các giai đoạn cần cập nhật: mặc định cả ba giai đoạn (1: thủ tục và cư trú; 2: các lĩnh vực còn lại;
    3: đăng ký khác với công an). Chọn một giai đoạn bằng --giai-doan=1, 2 hoặc 3."""
    for arg in sys.argv:
        if arg.startswith("--giai-doan="):
            return [int(arg.split("=", 1)[1])]
    return [1, 2, 3]


def _sync_chinh_thuc(conn, run_at, giai_doan):
    """Đọc ba nguồn chính thức theo giai đoạn. Lần đầu của mỗi nguồn duyệt toàn bộ lịch sử;
    lỗi một nguồn không chặn các nguồn khác."""
    keywords = nguon_chinh_thuc.tu_khoa_giai_doan(
        giai_doan, vbpl_sync.load_config()["tu_khoa_tim_van_ban_moi"]
    )
    fetcher = nguon_chinh_thuc.Fetcher()
    for nguon, reader in nguon_chinh_thuc.READERS.items():
        known = {row["url"]: row for row in store.load_chinh_thuc(conn, nguon)}
        toan_bo = store.get_state(conn, nguon_chinh_thuc.khoa_nen(nguon, giai_doan)) is None
        try:
            found = reader(fetcher, keywords, known, toan_bo)
            if found["tong"] == 0:
                raise RuntimeError("không đọc được mục nào từ trang")
            new = store.sync_chinh_thuc(conn, nguon, found["items"], run_at, giai_doan)
            conn.commit()
            che_do = "nạp đầu, duyệt toàn bộ" if toan_bo else "cập nhật"
            print(f"Nguồn {nguon} (giai đoạn {giai_doan}, {che_do}): "
                  f"{len(found['items'])} văn bản liên quan, {new} văn bản mới.")
        except BlockedError as error:
            conn.rollback()
            print(f"Nguồn {nguon} từ chối truy cập: {error}. Bỏ qua lần này.")
        except Exception as error:  # noqa: BLE001 - lỗi một nguồn không làm hỏng các nguồn khác
            conn.rollback()
            print(f"Nguồn {nguon} lỗi: {error}. Giữ dữ liệu cũ.")


def _chinh_thuc_trong_pham_vi(conn):
    """Văn bản chính thức đã lưu, bỏ thủ tục của ngành khác (không do công an). Dùng cho toàn văn và đối chiếu vbpl."""
    tu_khoa = nguon_chinh_thuc.tu_khoa_giai_doan(3, vbpl_sync.load_config()["tu_khoa_tim_van_ban_moi"])
    return nguon_chinh_thuc.loc_pham_vi(store.load_chinh_thuc(conn), tu_khoa)


def _sync_nguon_text(conn):
    """Toàn văn của văn bản nguồn chính thức (PDF). Lỗi ở đây không chặn cập nhật dữ liệu."""
    try:
        done, failed = nguon_text.sync_nguon_text(
            conn, nguon_chinh_thuc.Fetcher(), DOCS_DATA_DIR / "nguon_text", _chinh_thuc_trong_pham_vi(conn)
        )
        print(f"Toàn văn nguồn chính thức: thêm {done}, không đọc được {failed}.")
    except BlockedError as error:
        print(f"Toàn văn nguồn chính thức bị từ chối: {error}. Thử lại lần sau.")
    except Exception as error:  # noqa: BLE001
        print(f"Toàn văn nguồn chính thức lỗi: {error}. Giữ dữ liệu cũ.")


def _sync_cong_dvc(conn, run_at):
    """Thủ tục do công an từ Cổng Dịch vụ công Quốc gia. Lỗi ở đây không chặn các nguồn khác."""
    try:
        tong, chon, moi = cong_dvc.dong_bo(conn, run_at)
        print(f"Cổng quốc gia: {tong} thủ tục công khai; chọn {chon} thủ tục có công an; {moi} thay đổi.")
    except BlockedError as error:
        conn.rollback()
        print(f"Cổng quốc gia từ chối truy cập: {error}. Giữ dữ liệu cũ.")
    except Exception as error:  # noqa: BLE001 - lỗi một nguồn không làm hỏng các nguồn khác
        conn.rollback()
        print(f"Cổng quốc gia lỗi: {error}. Giữ dữ liệu cũ.")


def _sync_vbpl(conn, run_at):
    """Đọc trạng thái từ vbpl.vn. Lỗi ở bước này không chặn cập nhật từ cổng Phòng CSQLHC."""
    try:
        config = vbpl_sync.load_config()
        extra_numbers = [item["so_ky_hieu"] for item in json.loads(EXTRA_PATH.read_text(encoding="utf-8"))]
        extra_numbers += [row["so_ky_hieu"] for row in _chinh_thuc_trong_pham_vi(conn)]
        run_date = datetime.fromisoformat(run_at).date()
        count = vbpl_sync.sync(conn, extra_numbers, run_at, run_date, config)
        conn.commit()
        print(f"vbpl.vn: đã đọc trạng thái {count} văn bản.")
        texts = vbpl_text.sync_texts(conn, DOCS_DATA_DIR / "vbpl_text", config["do_tre_giua_cac_yeu_cau_giay"])
        print(f"vbpl.vn: đã lưu toàn văn {texts} văn bản có thay đổi.")
    except ImportError as error:
        conn.rollback()
        print(f"Bỏ qua vbpl.vn: thiếu thư viện ({error}). Cài Playwright để bật bước này.")
    except BlockedError as error:
        conn.commit()
        print(f"vbpl.vn chặn truy cập: {error}. Giữ dữ liệu cũ, không thử lại.")
    except Exception as error:  # noqa: BLE001 - lỗi vbpl không làm hỏng dữ liệu của cổng
        conn.commit()
        print(f"vbpl.vn lỗi: {error}. Giữ dữ liệu cũ.")


def _check_sanity(conn, kind, fresh_count):
    if fresh_count == 0:
        raise RuntimeError(f"{kind}: cổng trả về 0 bản ghi")
    previous = store.active_count(conn, kind)
    if previous and fresh_count < previous * MIN_RATIO:
        raise RuntimeError(f"{kind}: giảm từ {previous} xuống {fresh_count} bản ghi, nghi cổng lỗi")


def _save_raw_snapshot(run_at, raw_van_ban, raw_tthc):
    day_dir = RAW_DIR / run_at[:10]
    day_dir.mkdir(parents=True, exist_ok=True)
    stamp = run_at[11:19].replace(":", "")
    payload = {
        "van_ban": raw_van_ban,
        "tthc": [{"list": item, "detail": detail} for item, detail in raw_tthc],
    }
    (day_dir / f"snapshot_{stamp}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def _record_failure(conn, run_at, status):
    store.log_run(conn, run_at, status, 0, 0, 0)
    conn.commit()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(run())
