"""Chuẩn hóa bản ghi thô từ cổng thành dữ liệu sạch để so sánh thay đổi và xuất ra web."""

import hashlib
import json


def _text(value):
    return (value or "").strip()


def _strip_plus_prefix(value):
    # Cổng ghi tên căn cứ dạng "+ Luật 97/2015/QH13: ..." — bỏ tiền tố "+ ".
    return _text(value).lstrip("+").strip()


def _drop_ids(record):
    return {key: value for key, value in record.items() if not key.startswith("ID")}


def normalize_van_ban(raw):
    return {
        "id": raw["ID"],
        "so_ky_hieu": _text(raw.get("SO_KY_HIEU")),
        "loai": _text(raw.get("LOAI_VB")),
        "linh_vuc": _text(raw.get("LINH_VUC")),
        "co_quan_ban_hanh": _text(raw.get("CQ_BAN_HANH")),
        "nguoi_ky": _text(raw.get("NGUOI_KY")),
        "trich_yeu": _text(raw.get("TRICH_YEU")),
        "ngay_ban_hanh": _text(raw.get("NGAY_BAN_HANH")),
        "ngay_hieu_luc": _text(raw.get("NGAY_HIEU_LUC")),
        # Cờ "hiệu lực" của cổng. Cổng không cập nhật đầy đủ nên không dùng làm kết luận pháp lý.
        "hieu_luc_theo_cong": str(raw.get("HIEU_LUC")) == "1",
        "file_dinh_kem": _text(raw.get("FILE_NAME")),
    }


def normalize_tthc(list_item, detail):
    tthc = detail["TTHC"]
    return {
        "id": list_item["ID"],
        "ma_thu_tuc": _text(tthc.get("MA_THU_TUC")),
        "ten": _text(tthc.get("TEN_THU_TUC")) or _text(list_item.get("TEN_THU_TUC")),
        "linh_vuc": _text(tthc.get("LINH_VUC")) or _text(list_item.get("LINH_VUC")),
        "co_quan_thuc_hien": _text(tthc.get("CO_QUAN_THUC_HIEN")),
        "doi_tuong": _text(tthc.get("DOI_TUONG")),
        "thoi_han": _text(tthc.get("THOI_HAN_GIAI_QUYET")),
        "cach_thuc": _text(tthc.get("CACH_THUC_THUC_HIEN")),
        "thanh_phan_ho_so": _text(tthc.get("THANH_PHAN_HO_SO")),
        "trinh_tu": _text(tthc.get("TRINH_TU_THUC_HIEN")),
        "ket_qua": _text(tthc.get("KET_QUA")),
        "le_phi": [
            {
                "muc": _text(item.get("MUC_PHI")),
                "ten": _text(item.get("TEN_PHI")),
                "van_ban": _strip_plus_prefix(item.get("VAN_BAN")),
            }
            for item in detail.get("LEPHI", [])
        ],
        "can_cu": [
            _strip_plus_prefix(item.get("VAN_BAN"))
            for item in detail.get("CCPL", [])
            if _strip_plus_prefix(item.get("VAN_BAN"))
        ],
        "yeu_cau": [_drop_ids(item) for item in detail.get("YEUCAU", [])],
        "mau_don": [_drop_ids(item) for item in detail.get("MAUDON", [])],
        "hieu_luc_theo_cong": str(tthc.get("HIEU_LUC")) == "1",
    }


def content_hash(record):
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def diff_fields(old, new):
    """Trả về các trường khác nhau: {tên_trường: {"cu": ..., "moi": ...}}."""
    changed = {}
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            changed[key] = {"cu": old.get(key), "moi": new.get(key)}
    return changed
