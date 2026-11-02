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

from . import export, normalize, sources, store, vbpl_sync
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

    _sync_vbpl(conn, run_at)
    export.write_outputs(conn, DOCS_DATA_DIR, OVERRIDES_PATH, EXTRA_PATH, run_at)

    label = "lần đầu, ghi nhận nền" if first_run else f"{change_count} thay đổi"
    print(f"Xong. Văn bản: {len(van_ban)}, thủ tục: {len(tthc)}. {label}.")
    return 0


def _sync_vbpl(conn, run_at):
    """Đọc trạng thái từ vbpl.vn. Lỗi ở bước này không chặn cập nhật từ cổng Phòng CSQLHC."""
    try:
        config = vbpl_sync.load_config()
        extra_numbers = [item["so_ky_hieu"] for item in json.loads(EXTRA_PATH.read_text(encoding="utf-8"))]
        run_date = datetime.fromisoformat(run_at).date()
        count = vbpl_sync.sync(conn, extra_numbers, run_at, run_date, config)
        conn.commit()
        print(f"vbpl.vn: đã đọc trạng thái {count} văn bản.")
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
