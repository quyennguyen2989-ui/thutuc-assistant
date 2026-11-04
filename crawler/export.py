"""Xuất dữ liệu thành JSON tĩnh cho trang web (docs/data/).

Ngoài dữ liệu tự động từ cổng, có thêm hai tệp đối chiếu thủ công:
- tinh_trang_thu_cong.json: ghi chú tình trạng hiệu lực khi cổng đánh dấu sai hoặc chưa cập nhật.
- van_ban_bo_sung.json: văn bản quan trọng cổng chưa có (kèm nguồn đối chiếu).
Mỗi mục đều ghi nguồn và ngày đối chiếu, để người dùng tự kiểm tra lại.
"""

import json
import re
from pathlib import Path

from . import nguon_chinh_thuc, nguon_trang_thai, normalize, store, vbpl, vbpl_sync

SOURCE_PORTAL = {
    "ten": "Trang thông tin điện tử Phòng Cảnh sát quản lý hành chính về trật tự xã hội (Công an TP.HCM)",
    "url": "https://qlhc-congan.hochiminhcity.gov.vn/wps/portal/Home/vbpq",
}

SOURCE_VBPL = {
    "ten": "Cơ sở dữ liệu quốc gia về pháp luật (vbpl.vn)",
    "url": vbpl.SITE,
}

# Mọi nơi dự án thu thập thông tin; trang web hiển thị danh sách này ở chân trang.
NGUON_THU_THAP = [
    {"ten": "Cổng Phòng CSQLHC Công an TP.HCM (thủ tục, văn bản pháp quy)", "url": SOURCE_PORTAL["url"]},
    {"ten": "Cổng thông tin Công an TP.HCM (tin nêu chỉ đạo, triển khai)", "url": "https://congan.hochiminhcity.gov.vn/"},
    {"ten": "Cổng Dịch vụ công Quốc gia (thủ tục có Công an)", "url": "https://dichvucong.gov.vn/"},
    {"ten": "Công báo điện tử Chính phủ", "url": "https://congbao.chinhphu.vn/"},
    {"ten": "Công báo TP.HCM", "url": "https://congbao.hochiminhcity.gov.vn/"},
    {"ten": "Cổng thông tin Bộ Công an (hệ thống văn bản)", "url": "https://vanban.bocongan.gov.vn/"},
    {"ten": "Cơ sở dữ liệu quốc gia về pháp luật (vbpl.vn)", "url": vbpl.SITE},
]

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
        record["so_ky_hieu"] = normalize.chuan_so_ky_hieu(record["so_ky_hieu"] or "")
        override = overrides.get(record["so_ky_hieu"])
        if override:
            record["doi_chieu_thu_cong"] = override
        items.append(record)
    for entry in extra:
        items.append({**entry, "id": None, "nguon": "thu_cong", "hieu_luc_theo_cong": None, "_missing": False})
    return items


def _nam_cua(row):
    """Năm ban hành suy ra từ số ký hiệu (…/2006/…), hoặc năm hiệu lực nếu không có số."""
    match = re.search(r"/(\d{4})/", row.get("so_ky_hieu") or "")
    if match:
        return int(match.group(1))
    ngay = row.get("ngay_hieu_luc") or ""
    return int(ngay[:4]) if ngay[:4].isdigit() else None


def _trong_pham_vi(row, cited, tu_khoa=()):
    """Văn bản vbpl.vn có đưa vào dữ liệu không.

    Lấy: căn cứ của thủ tục đang theo dõi; văn bản từ 2025 trở đi; văn bản còn (một phần) hiệu lực.
    Bỏ: thủ tục hành chính của ngành khác (không do công an); văn bản đã hết hiệu lực từ 2025 trở về trước
    và không phải căn cứ của thủ tục.
    """
    if row.get("so_ky_hieu") in cited:
        return True
    ten = row.get("trich_yeu") or row.get("tieu_de") or ""
    if nguon_chinh_thuc.ngoai_pham_vi_thu_tuc(ten, row.get("so_ky_hieu") or "",
                                              row.get("co_quan_ban_hanh") or "", tu_khoa):
        return False
    nam = _nam_cua(row)
    if nam is not None and nam >= vbpl_sync.NAM_BAT_DAU_LICH_SU:
        return True
    tinh_trang = row.get("tinh_trang") or ""
    return tinh_trang.startswith(("Còn hiệu lực", "Chưa có hiệu lực", "Hết hiệu lực một phần"))


def _can_cu_dang_theo_doi(tthc):
    """Số ký hiệu của mọi căn cứ pháp lý trong các thủ tục đang theo dõi."""
    found = set()
    for item in tthc:
        for title in item.get("can_cu") or []:
            found.update(vbpl.NUMBER_IN_TEXT.findall(title))
    return found


def _merge_vbpl(items, rows, keywords, cited=frozenset(), tu_khoa=()):
    """Gắn trạng thái đọc từ vbpl.vn vào văn bản đã có, hoặc thêm văn bản mới tìm được.

    Chỉ lấy văn bản có trạng thái và còn thuộc phạm vi hiện tại (theo số ký hiệu hoặc từ khóa).
    """
    by_number = {item["so_ky_hieu"]: item for item in items}
    for row in rows:
        if not row["tinh_trang"]:
            continue
        if not (row["so_ky_hieu"] or vbpl.is_relevant(row["url"], row["sheet"], keywords)):
            continue
        # Văn bản không có số ký hiệu: lấy tiêu đề làm nhãn, không dùng đường dẫn vbpl.vn.
        number = normalize.chuan_so_ky_hieu(row["so_ky_hieu"] or _number_from_title(row["tieu_de"]) or "") or (row["tieu_de"] or "").strip() or row["url"]
        vbpl_info = {
            "url": row["url"],
            "tinh_trang": row["tinh_trang"],
            "ngay_hieu_luc": row["ngay_hieu_luc"],
            "ngay_cap_nhat": row["ngay_cap_nhat"],
            "kiem_tra_luc": row["kiem_tra_luc"],
            "lich_su": json.loads(row["lich_su"]) if row["lich_su"] else None,
        }
        if number in by_number:
            by_number[number]["vbpl"] = vbpl_info
            continue
        if not _trong_pham_vi(row, cited, tu_khoa):
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


def _so_key(number):
    """Khóa so khớp số ký hiệu: bỏ khoảng trắng, Đ thành D, không phân biệt hoa thường."""
    return re.sub(r"\s+", "", number or "").upper().replace("Đ", "D")


def _merge_chinh_thuc(items, rows, vbpl_rows=(), cited=frozenset(), tu_khoa=()):
    """Gắn nguồn chính thức vào văn bản đã có cùng số ký hiệu, hoặc thêm văn bản chỉ có ở nguồn chính thức.

    Văn bản chính thức cũ (trước 2025) chỉ thêm khi vbpl.vn cho biết còn hiệu lực hoặc là căn cứ của thủ tục.
    """
    by_key = {}
    for item in items:
        key = _so_key(item["so_ky_hieu"])
        if key:
            by_key.setdefault(key, item)
    vbpl_status = {}
    for vb in vbpl_rows:
        key = _so_key(vb.get("so_ky_hieu"))
        if key and vb.get("tinh_trang"):
            vbpl_status.setdefault(key, vb["tinh_trang"])
    for row in rows:
        source = {
            "ten": nguon_chinh_thuc.TEN_NGUON[row["nguon"]],
            "url": row["url"],
            "ngay_ban_hanh": row["ngay_ban_hanh"] or "",
        }
        key = _so_key(row["so_ky_hieu"])
        if not key:
            continue
        if key in by_key:
            by_key[key].setdefault("nguon_chinh_thuc", []).append(source)
            continue
        probe = {
            "so_ky_hieu": row["so_ky_hieu"],
            "trich_yeu": row["trich_yeu"] or "",
            "co_quan_ban_hanh": row["co_quan_ban_hanh"] or "",
            "ngay_hieu_luc": row["ngay_hieu_luc"] or "",
            "tinh_trang": vbpl_status.get(key, ""),
        }
        if not _trong_pham_vi(probe, cited, tu_khoa):
            continue
        item = {
            "id": None,
            "so_ky_hieu": row["so_ky_hieu"],
            "loai": row["loai"] or "",
            "linh_vuc": "",
            "co_quan_ban_hanh": row["co_quan_ban_hanh"] or "",
            "nguoi_ky": "",
            "trich_yeu": row["trich_yeu"] or "",
            "ngay_ban_hanh": row["ngay_ban_hanh"] or "",
            "ngay_hieu_luc": row["ngay_hieu_luc"] or "",
            "hieu_luc_theo_cong": None,
            "file_dinh_kem": "",
            "nguon": "chinh_thuc",
            "nguon_chinh_thuc": [source],
            "_missing": False,
        }
        items.append(item)
        by_key[key] = item
    return items


def _ngay_cap_nhat(item, thay_doi):
    """Ngày cập nhật mới nhất của một văn bản hoặc thủ tục, kèm nguồn của ngày đó.

    Ưu tiên ngày do nguồn công bố (vbpl.vn, đối chiếu thủ công, ngày ban hành công báo);
    nếu không có thì dùng ngày hệ thống phát hiện thay đổi, hoặc ngày ghi nhận lần đầu.
    """
    vb = item.get("vbpl") or {}
    if vb.get("ngay_cap_nhat"):
        return vb["ngay_cap_nhat"], "vbpl.vn cập nhật trang văn bản"
    dc = item.get("doi_chieu_thu_cong") or {}
    if dc.get("ngay_doi_chieu"):
        return dc["ngay_doi_chieu"], "đối chiếu thủ công"
    if item.get("nguon") == "chinh_thuc" and item.get("ngay_ban_hanh"):
        return item["ngay_ban_hanh"], "ngày ban hành trên công báo"
    run_at = thay_doi.get(item.get("id"))
    if run_at:
        return run_at[:10], "hệ thống phát hiện thay đổi trên cổng"
    if item.get("_first_seen"):
        return item["_first_seen"][:10], "ghi nhận lần đầu, cổng không ghi ngày cập nhật"
    return "", ""


def _number_from_title(title):
    match = vbpl.NUMBER_IN_TEXT.search(title or "")
    return match.group(0) if match else None


def _last_ok_run(conn):
    row = conn.execute(
        "SELECT run_at FROM runs WHERE status = 'ok' ORDER BY run_at DESC LIMIT 1"
    ).fetchone()
    return row["run_at"] if row else None


def _chi_dao_catp(conn):
    """Tin nêu chỉ đạo, triển khai của Công an TP.HCM, mới nhất trước. Tóm tắt rút gọn để trang web nhẹ."""
    return [
        {**tin, "tom_tat": tin["tom_tat"][:300]}
        for tin in store.load_tin_catp(conn)
    ]


def _trang_thai_nguon(conn):
    """Trạng thái gần nhất của từng nguồn: đọc được, lỗi, bị chặn; kèm lần đọc thành công gần nhất."""
    status = store.load_nguon_status(conn)
    return {
        nguon: {
            "ten": nguon_trang_thai.ten(nguon),
            "trang_thai": item["trang_thai"],
            "thong_bao": item["thong_bao"],
            "luc": item["luc"],
            "thanh_cong_gan_nhat": item["thanh_cong_gan_nhat"],
        }
        for nguon, item in sorted(status.items())
    }


def write_outputs(conn, out_dir, overrides_path, extra_path, run_at):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    overrides = {item["so_ky_hieu"]: item for item in _read_json(overrides_path, [])}
    extra = _read_json(extra_path, [])

    keywords = vbpl_sync.load_config()["tu_khoa_tim_van_ban_moi"]
    tu_khoa = nguon_chinh_thuc.tu_khoa_giai_doan(3, keywords)
    # Thủ tục từ cổng quốc gia (chỉ phần do công an) nằm cùng danh mục với thủ tục của cổng TP.HCM.
    tthc = store.load_records(conn, "tthc") + store.load_records(conn, "tthc_qg")
    cited = _can_cu_dang_theo_doi(tthc)
    van_ban = _merge_vbpl(_van_ban_view(conn, overrides, extra), store.load_vbpl(conn), keywords, cited, tu_khoa)
    van_ban = _merge_chinh_thuc(van_ban, store.load_chinh_thuc(conn), store.load_vbpl(conn), cited, tu_khoa)
    changes = store.load_changes(conn)

    thay_doi_van_ban = store.last_change_dates(conn, "van_ban")
    for item in van_ban:
        item["ngay_cap_nhat"], item["nguon_ngay_cap_nhat"] = _ngay_cap_nhat(item, thay_doi_van_ban)
    thay_doi_tthc = store.last_change_dates(conn, "tthc")
    for item in tthc:
        item["ngay_cap_nhat"], item["nguon_ngay_cap_nhat"] = _ngay_cap_nhat(item, thay_doi_tthc)

    meta = {
        "cap_nhat_luc": run_at,
        "lan_chay_thanh_cong_gan_nhat": _last_ok_run(conn),
        "trang_thai_nguon": _trang_thai_nguon(conn),
        "so_van_ban": len(van_ban),
        "so_thu_tuc": len(tthc),
        "nguon": SOURCE_PORTAL,
        "nguon_van_ban": SOURCE_VBPL,
        "nguon_thu_thap": NGUON_THU_THAP,
        "nguon_chinh_thuc": [
            {"ten": nguon_chinh_thuc.TEN_NGUON[nguon], "url": url}
            for nguon, url in nguon_chinh_thuc.DIA_CHI_TRANG.items()
        ],
        "luu_y": DISCLAIMER,
    }

    _write(out_dir / "van_ban.json", van_ban)
    _write(out_dir / "tthc.json", tthc)
    _write(out_dir / "thay_doi.json", changes)
    _write(out_dir / "meta.json", meta)
    _write(out_dir / "chi_dao_catp.json", _chi_dao_catp(conn))


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
