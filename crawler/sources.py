"""Các điểm truy cập JSON của cổng.

Đã kiểm tra trực tiếp trên trang ngày 2026-11-02:
- Văn bản pháp quy: VBPQ/view/getListVanBan.do (31 bản ghi)
- Thủ tục hành chính: PA_TTHC/view/getListTTHC.do (42 thủ tục)
- Chi tiết thủ tục: PA_TTHC/view/getItemTTHC.do?ID=... (hồ sơ, trình tự, thời hạn, lệ phí, căn cứ)
Tệp đính kèm (downloadFile.do) trả về 403 nên không dùng ở bước này.
"""

PAGE_SIZE = 100


def _fetch_all(client, path, extra_params=None):
    """Lấy toàn bộ bản ghi, tự phân trang theo trường NUMBER_RECORD."""
    records = []
    page = 1
    while True:
        params = {"sortOrder": "asc", "pageSize": PAGE_SIZE, "pageNumber": page}
        params.update(extra_params or {})
        payload = client.get_json(path, params)
        batch = payload.get("message") or []
        if not isinstance(batch, list):
            raise RuntimeError(f"Dữ liệu từ {path} không đúng định dạng")
        records.extend(batch)
        total = batch[0].get("NUMBER_RECORD", 0) if batch else 0
        if not batch or len(records) >= total:
            return records
        page += 1


def fetch_van_ban(client):
    return _fetch_all(client, "VBPQ/view/getListVanBan.do")


def fetch_tthc_list(client):
    return _fetch_all(client, "PA_TTHC/view/getListTTHC.do", {"NOI_DUNG": "", "ID_LINH_VUC": ""})


def fetch_tthc_detail(client, tthc_id):
    payload = client.get_json("PA_TTHC/view/getItemTTHC.do", {"ID": tthc_id})
    if payload.get("status") != "success":
        raise RuntimeError(f"Không lấy được chi tiết thủ tục ID={tthc_id}")
    return payload["message"]
