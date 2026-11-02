"""Xuất dữ liệu thành JSON tĩnh cho trang web (docs/data/).

Ngoài dữ liệu tự động từ cổng, có thêm hai tệp đối chiếu thủ công:
- tinh_trang_thu_cong.json: ghi chú tình trạng hiệu lực khi cổng đánh dấu sai hoặc chưa cập nhật.
- van_ban_bo_sung.json: văn bản quan trọng cổng chưa có (kèm nguồn đối chiếu).
Mỗi mục đều ghi nguồn và ngày đối chiếu, để người dùng tự kiểm tra lại.
"""

import json
from pathlib import Path

from . import store

SOURCE_PORTAL = {
    "ten": "Trang thông tin điện tử Phòng Cảnh sát quản lý hành chính về trật tự xã hội (Công an TP.HCM)",
    "url": "https://qlhc-congan.hochiminhcity.gov.vn/wps/portal/Home/vbpq",
}

DISCLAIMER = (
    "Công cụ hỗ trợ tra cứu, không thay thế văn bản pháp luật chính thức và không phải ý kiến pháp lý. "
    "Trước khi áp dụng, đối chiếu với văn bản gốc trên Cơ sở dữ liệu quốc gia về văn bản pháp luật hoặc Công báo."
)


def _read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _van_ban_view(conn, overrides, extra):
    items = []
    for record in store.load_records(conn, "van_ban"):
        record["nguon"] = "cong_tu_dong"
        override = overrides.get(record["so_ky_hieu"])
        if override:
            record["doi_chieu_thu_cong"] = override
        items.append(record)
    for entry in extra:
        items.append({**entry, "id": None, "nguon": "thu_cong", "hieu_luc_theo_cong": None, "_missing": False})
    return items


def _last_ok_run(conn):
    row = conn.execute(
        "SELECT run_at FROM runs WHERE status = 'ok' ORDER BY run_at DESC LIMIT 1"
    ).fetchone()
    return row["run_at"] if row else None


def write_outputs(conn, out_dir, overrides_path, extra_path, run_at):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    overrides = {item["so_ky_hieu"]: item for item in _read_json(overrides_path, [])}
    extra = _read_json(extra_path, [])

    van_ban = _van_ban_view(conn, overrides, extra)
    tthc = store.load_records(conn, "tthc")
    changes = store.load_changes(conn)

    meta = {
        "cap_nhat_luc": run_at,
        "lan_chay_thanh_cong_gan_nhat": _last_ok_run(conn),
        "so_van_ban": len(van_ban),
        "so_thu_tuc": len(tthc),
        "nguon": SOURCE_PORTAL,
        "luu_y": DISCLAIMER,
    }

    _write(out_dir / "van_ban.json", van_ban)
    _write(out_dir / "tthc.json", tthc)
    _write(out_dir / "thay_doi.json", changes)
    _write(out_dir / "meta.json", meta)


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
