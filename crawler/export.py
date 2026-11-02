"""Xuất dữ liệu thành JSON tĩnh cho trang web (docs/data/).

Ngoài dữ liệu tự động từ cổng, có thêm hai tệp đối chiếu thủ công:
- tinh_trang_thu_cong.json: ghi chú tình trạng hiệu lực khi cổng đánh dấu sai hoặc chưa cập nhật.
- van_ban_bo_sung.json: văn bản quan trọng cổng chưa có (kèm nguồn đối chiếu).
Mỗi mục đều ghi nguồn và ngày đối chiếu, để người dùng tự kiểm tra lại.
"""

import json
from pathlib import Path

from . import store, vbpl, vbpl_sync

SOURCE_PORTAL = {
    "ten": "Trang thông tin điện tử Phòng Cảnh sát quản lý hành chính về trật tự xã hội (Công an TP.HCM)",
    "url": "https://qlhc-congan.hochiminhcity.gov.vn/wps/portal/Home/vbpq",
}

SOURCE_VBPL = {
    "ten": "Cơ sở dữ liệu quốc gia về pháp luật (vbpl.vn)",
    "url": vbpl.SITE,
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


def _merge_vbpl(items, rows, keywords):
    """Gắn trạng thái đọc từ vbpl.vn vào văn bản đã có, hoặc thêm văn bản mới tìm được.

    Chỉ lấy văn bản có trạng thái và còn thuộc phạm vi hiện tại (theo số ký hiệu hoặc từ khóa).
    """
    by_number = {item["so_ky_hieu"]: item for item in items}
    for row in rows:
        if not row["tinh_trang"]:
            continue
        if not (row["so_ky_hieu"] or vbpl.is_relevant(row["url"], row["sheet"], keywords)):
            continue
        number = row["so_ky_hieu"] or _number_from_title(row["tieu_de"]) or row["url"]
        vbpl_info = {
            "url": row["url"],
            "tinh_trang": row["tinh_trang"],
            "ngay_hieu_luc": row["ngay_hieu_luc"],
            "ngay_cap_nhat": row["ngay_cap_nhat"],
            "kiem_tra_luc": row["kiem_tra_luc"],
        }
        if number in by_number:
            by_number[number]["vbpl"] = vbpl_info
            continue
        item = {
            "id": None,
            "so_ky_hieu": number,
            "loai": "",
            "linh_vuc": "",
            "co_quan_ban_hanh": "",
            "nguoi_ky": "",
            "trich_yeu": row["tieu_de"] or "",
            "ngay_ban_hanh": "",
            "ngay_hieu_luc": row["ngay_hieu_luc"] or "",
            "hieu_luc_theo_cong": None,
            "file_dinh_kem": "",
            "nguon": "vbpl",
            "vbpl": vbpl_info,
            "_missing": False,
        }
        items.append(item)
        by_number[number] = item
    return items


def _number_from_title(title):
    match = vbpl.NUMBER_IN_TEXT.search(title or "")
    return match.group(0) if match else None


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

    keywords = vbpl_sync.load_config()["tu_khoa_tim_van_ban_moi"]
    van_ban = _merge_vbpl(_van_ban_view(conn, overrides, extra), store.load_vbpl(conn), keywords)
    tthc = store.load_records(conn, "tthc")
    changes = store.load_changes(conn)

    meta = {
        "cap_nhat_luc": run_at,
        "lan_chay_thanh_cong_gan_nhat": _last_ok_run(conn),
        "so_van_ban": len(van_ban),
        "so_thu_tuc": len(tthc),
        "nguon": SOURCE_PORTAL,
        "nguon_van_ban": SOURCE_VBPL,
        "luu_y": DISCLAIMER,
    }

    _write(out_dir / "van_ban.json", van_ban)
    _write(out_dir / "tthc.json", tthc)
    _write(out_dir / "thay_doi.json", changes)
    _write(out_dir / "meta.json", meta)


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
