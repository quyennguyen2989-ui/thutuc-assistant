"""Thủ tục từ Cổng Dịch vụ công Quốc gia, phần do công an thực hiện hoặc có công an tham gia.

Nguồn: các API công khai mà trang tra cứu thủ tục đọc (không đăng nhập, không đọc hồ sơ cá nhân).
Lọc: đơn vị thực hiện hoặc ban hành có công an, và tên khớp một lĩnh vực quản lý dân cư
(cùng bộ từ khóa với văn bản; từ khóa chung "thủ tục hành chính" không tính).
Gọi chậm; lỗi mạng thì thử lại; 401, 403, 429 thì dừng ngay và không thử lại.

Chạy: python -m crawler.cong_dvc
"""

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from . import nguon_chinh_thuc, store, vbpl_sync
from .client import BlockedError

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "thutuc.db"

BASE_URL = "https://dichvucong.gov.vn/api/v1"
DANH_SACH_PATH = "/submitting/formality/list-all-public-formality-by-citizen"
CHI_TIET_PATH = "/configuring/formality/get-formality-by-citizen"
USER_AGENT = "thutuc-assistant/0.1 (open-source, cong cu tra cuu van ban cho can bo dan cu)"
SO_MOI_TRANG = 100
DO_TRE_GIAY = 1.5
THU_LAI = 3
KHOA_NEN = "cong_dvc:nen"
NGUON_TEN = "Cổng Dịch vụ công Quốc gia (Bộ Công an)"
NGUON_URL = "https://dichvucong.gov.vn/"
CHO_TRONG = "chưa quy định cụ thể"


class DvcClient:
    """Gọi API công khai bằng POST JSON, chậm và có User-Agent rõ ràng."""

    def __init__(self, delay_seconds=DO_TRE_GIAY, timeout=60.0):
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self._last = 0.0

    def _cho_luot(self):
        elapsed = time.monotonic() - self._last
        if elapsed < self.delay_seconds:
            time.sleep(self.delay_seconds - elapsed)

    def post(self, path, body):
        data = json.dumps(body).encode("utf-8")
        last_error = None
        for attempt in range(1, THU_LAI + 1):
            self._cho_luot()
            request = urllib.request.Request(
                BASE_URL + path,
                data=data,
                method="POST",
                headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self._last = time.monotonic()
                if payload.get("code") != "OK":
                    raise RuntimeError(f"{path} trả về mã {payload.get('code')}")
                return payload["data"]
            except urllib.error.HTTPError as error:
                self._last = time.monotonic()
                if error.code in (401, 403, 429):
                    raise BlockedError(f"HTTP {error.code} khi gọi {path}") from error
                last_error = error
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                self._last = time.monotonic()
                last_error = error
            time.sleep(5 * attempt)
        raise RuntimeError(f"gọi {path} thất bại sau {THU_LAI} lần: {last_error}")


def liet_ke(client):
    """Toàn bộ thủ tục công khai, phân trang theo mã của mục cuối. Thiếu so với tổng số thì báo lỗi."""
    items, last = [], ""
    tong = None
    while True:
        data = client.post(
            DANH_SACH_PATH,
            {"limit": SO_MOI_TRANG, "lastId": last, "q": "", "categoryId": "", "departmentCode": ""},
        )
        if tong is None:
            tong = data.get("total") or 0
        batch = data.get("items") or []
        items.extend(batch)
        next_last = data.get("lastId") or ""
        if not batch or len(batch) < SO_MOI_TRANG or not next_last or next_last == last:
            break
        last = next_last
    if len(items) < tong:
        raise RuntimeError(f"danh sách thiếu: đọc {len(items)} trên tổng {tong}, không ghi dữ liệu")
    return items


def do_cong_an(item):
    """Thủ tục do công an thực hiện hoặc có công an tham gia (theo đơn vị thực hiện và đơn vị ban hành)."""
    don_vi = list(item.get("departments") or []) + [item.get("departmentPromulgate") or ""]
    return any(nguon_chinh_thuc.co_cum(nguon_chinh_thuc.slug(ten), "cong-an") for ten in don_vi if ten)


def trong_linh_vuc(item, tu_khoa):
    """Tên thủ tục khớp một lĩnh vực quản lý dân cư. Từ khóa chung 'thủ tục hành chính' không tính."""
    khoa = [k for k in tu_khoa if k != nguon_chinh_thuc.THU_TUC_HANH_CHINH]
    return nguon_chinh_thuc.phu_hop(item.get("name") or "", khoa)


def la_khai_sinh(item):
    """Thủ tục khai sinh và cấp bản sao khai sinh. Khai sinh do UBND cấp xã (Tư pháp) làm, không cần công an:
    đây là bước đầu của đăng ký cư trú cho trẻ mới sinh, nên được đưa vào cùng danh mục."""
    return nguon_chinh_thuc.co_cum(nguon_chinh_thuc.slug(item.get("name") or ""), "khai-sinh")


def _ten_cac_muc(danh_sach, khoa="name"):
    return [str(x.get(khoa)).strip() for x in danh_sach or [] if x.get(khoa)]


def chuan_hoa(item, ct):
    """Đưa một thủ tục của cổng quốc gia về cùng các trường với tthc.json của cổng TP.HCM."""
    ma = item.get("code") or ct.get("code") or ""
    cac_buoc = [str(s.get("description", "")).strip() for s in ct.get("executionSteps") or [] if s.get("description")]
    thoi_han = next(
        (str(m.get("description")).strip() for m in ct.get("executionMethods") or [] if m.get("description")),
        CHO_TRONG,
    )
    giay_to = []
    for case in ct.get("executionCases") or []:
        for pc in case.get("profileComponents") or []:
            if pc.get("name"):
                giay_to.append(f"- {str(pc['name']).strip()}")
    yeu_cau = (ct.get("requirementsAndConditions") or "").strip()
    le_phi = [
        {"ten": str(f["name"]).strip(), "muc": str(f.get("amount", "") or ""), "van_ban": str(f.get("legalBasis", "") or "")}
        for f in ct.get("fees") or []
        if isinstance(f, dict) and f.get("name")
    ]
    linh_vuc = ", ".join(item.get("categories") or []) or ", ".join(_ten_cac_muc(ct.get("categoriesDetails")))
    return {
        "id": int(ma.replace(".", "")),
        "ma_thu_tuc": ma,
        "ten": (ct.get("name") or item.get("name") or "").strip(),
        "linh_vuc": linh_vuc,
        "co_quan_thuc_hien": ct.get("executingAgencies") or "; ".join(_ten_cac_muc(ct.get("departmentsExecuting"))),
        "co_quan_ban_hanh": ct.get("departmentPromulgateName") or "",
        "doi_tuong": "; ".join(_ten_cac_muc(ct.get("subjectTypesDetails"))),
        "thoi_han": thoi_han,
        "cach_thuc": "Trực tuyến trên Cổng Dịch vụ công quốc gia"
        if any(m.get("submissionMethod") == "ONLINE" for m in ct.get("executionMethods") or [])
        else (ct.get("dossierReceivingAddresses") or ""),
        "thanh_phan_ho_so": "\n".join(giay_to),
        "trinh_tu": "\n\n".join(cac_buoc),
        "ket_qua": "\n".join(_ten_cac_muc(ct.get("resultsDetails"))),
        "le_phi": le_phi,
        "can_cu": _ten_cac_muc(ct.get("legalBasisesDetails")),
        "yeu_cau": [{"FILE_NAME": "", "VAN_BAN": "", "NOI_DUNG": yeu_cau}] if yeu_cau and yeu_cau != "Không" else [],
        "mau_don": [],
        "hieu_luc_theo_cong": (ct.get("state") or item.get("state")) == "ACTIVE",
        "nguon": "cong_dvc_quoc_gia",
        "nguon_ten": NGUON_TEN,
        "url": NGUON_URL + "thu-tuc-hanh-chinh/" + str(item.get("id", "")),
    }


def dong_bo(conn, run_at, client=None):
    """Đọc danh sách, chọn thủ tục công an liên quan, tải chi tiết và ghi vào DB. Trả về (tổng, số chọn, số thay đổi)."""
    client = client or DvcClient()
    tu_khoa = nguon_chinh_thuc.tu_khoa_giai_doan(3, vbpl_sync.load_config()["tu_khoa_tim_van_ban_moi"])
    items = liet_ke(client)
    # Thủ tục trùng tên với thủ tục của cổng TP.HCM thì giữ bản TP.HCM (chi tiết theo địa phương).
    ten_da_co = {nguon_chinh_thuc.slug(r["ten"]) for r in store.load_records(conn, "tthc") if r.get("ten")}
    chon = [
        it for it in items
        if (do_cong_an(it) and trong_linh_vuc(it, tu_khoa) or la_khai_sinh(it))
        and nguon_chinh_thuc.slug(it["name"]) not in ten_da_co
    ]
    records = []
    ma_da_thay = set()
    for item in chon:
        ct = client.post(CHI_TIET_PATH, {"id": item["id"]})
        record = chuan_hoa(item, ct)
        if record["id"] in ma_da_thay:
            raise RuntimeError(f"trùng mã thủ tục {record['ma_thu_tuc']}, không ghi dữ liệu")
        ma_da_thay.add(record["id"])
        records.append(record)
    first_run = store.get_state(conn, KHOA_NEN) is None
    moi = store.sync_records(conn, "tthc_qg", records, run_at, first_run)
    store.set_state(conn, KHOA_NEN, run_at)
    conn.commit()
    return len(items), len(records), moi


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = store.connect(DB_PATH)
    run_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        tong, chon, moi = dong_bo(conn, run_at)
    except BlockedError as error:
        print(f"Cổng quốc gia từ chối truy cập: {error}. Dừng, thử lại sau.")
        return 2
    print(f"Cổng quốc gia: {tong} thủ tục công khai; chọn {chon} thủ tục có công an; {moi} thay đổi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
