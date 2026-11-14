"""Điểm vào chính: python -m crawler.update

Tải dữ liệu từ cổng, so với lần trước, ghi nhận thay đổi, rồi xuất JSON cho trang web.
Mỗi nguồn ghi trạng thái riêng (đọc được, lỗi, bị chặn, bỏ qua) vào meta.json, mục trang_thai_nguon.

Mã thoát:
  0  thành công, mọi nguồn đọc được (hoặc được bỏ qua theo tham số)
  1  lỗi (mạng, dữ liệu bất thường) — cổng chính không ghi dữ liệu mới
  2  máy chủ từ chối truy cập (403/401/429) — dừng ngay, không thử lại
  3  hoàn thành nhưng có nguồn lỗi (có thể thử lại) — dữ liệu các nguồn khác đã được ghi
  4  hoàn thành nhưng có nguồn bị chặn truy cập — không thử lại
"""

import json
import sys
from datetime import datetime
from pathlib import Path

from . import cong_dvc, export, nguon_phaplyvn, nguon_catp, normalize, nguon_chinh_thuc, nguon_text, nguon_trang_thai, sources, store, vbpl_sync, vbpl_text
from .client import BlockedError, PortalClient
from .nguon_trang_thai import BI_CHAN, BO_QUA, LOI, OK

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "thutuc.db"
RAW_DIR = ROOT / "data" / "raw"
DOCS_DATA_DIR = ROOT / "docs" / "data"
OVERRIDES_PATH = ROOT / "crawler" / "tinh_trang_thu_cong.json"
EXTRA_PATH = ROOT / "crawler" / "van_ban_bo_sung.json"

# Nếu số bản ghi giảm quá nửa so với lần trước, coi là cổng lỗi và không ghi gì.
MIN_RATIO = 0.5


# Cổng Dịch vụ công Quốc gia thường quá giờ khi chạy trên máy chủ CI (đã thử qua trình duyệt nhưng vẫn quá giờ).
# Lỗi của nguồn này chỉ ghi vào trang_thai_nguon, không làm lần chạy báo lỗi, để khỏi có thư lỗi mỗi ngày.
# Nếu cổng từ chối truy cập (bị chặn) thì vẫn báo lỗi như thường.
NGUON_CHI_GHI_NHAN = frozenset({"cong_dvc_quoc_gia", "phaplyvn"})
# Nguồn phụ (thứ cấp): kể cả bị chặn cũng không làm lần chạy báo lỗi.
NGUON_PHU = frozenset({"phaplyvn"})


def run():
    run_at = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = store.connect(DB_PATH)
    ghi = nguon_trang_thai.Ghi(conn, run_at)

    code = _chay(conn, run_at, ghi)
    ghi.tom_tat()
    if code == 0 and ghi.co_bi_chan(bo_qua=NGUON_PHU):
        print("Có nguồn bị chặn truy cập. Không thử lại để tránh bị chặn thêm.")
        return 4
    if code == 0 and ghi.co_loi(bo_qua=NGUON_CHI_GHI_NHAN, bo_qua_hoan_toan=NGUON_PHU):
        print("Có nguồn lỗi. Dữ liệu các nguồn khác đã được ghi; xem trang_thai_nguon trong meta.json.")
        return 3
    return code


def _chay(conn, run_at, ghi):
    client = PortalClient()

    try:
        raw_van_ban = sources.fetch_van_ban(client)
        raw_tthc = []
        for item in sources.fetch_tthc_list(client):
            raw_tthc.append((item, sources.fetch_tthc_detail(client, item["ID"])))
    except BlockedError as error:
        _record_failure(conn, run_at, f"bi_chan: {error}")
        ghi.ghi("cong_phong_csqlhc", BI_CHAN, str(error))
        print(f"DỪNG: {error}. Không thử lại để tránh bị chặn thêm.")
        return 2
    except Exception as error:  # noqa: BLE001 - ghi nhận mọi lỗi mạng/dữ liệu rồi thoát
        _record_failure(conn, run_at, f"loi: {error}")
        ghi.ghi("cong_phong_csqlhc", LOI, str(error))
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
        ghi.ghi("cong_phong_csqlhc", LOI, f"bất thường: {error}")
        print(f"BẤT THƯỜNG: {error}. Không ghi dữ liệu.")
        return 1

    with conn:
        first_run = store.is_first_run(conn)
        change_count = store.sync_records(conn, "van_ban", van_ban, run_at, first_run)
        change_count += store.sync_records(conn, "tthc", tthc, run_at, first_run)
        store.log_run(conn, run_at, "ok", len(van_ban), len(tthc), change_count)
    ghi.ghi("cong_phong_csqlhc", OK, f"{len(van_ban)} văn bản, {len(tthc)} thủ tục")

    if "--khong-chinh-thuc" not in sys.argv:
        for giai_doan in _cac_giai_doan():
            _sync_chinh_thuc(conn, run_at, giai_doan, ghi)
        _sync_nguon_text(conn, ghi)
    else:
        _bo_qua(ghi, list(nguon_chinh_thuc.READERS) + ["toan_van"], "--khong-chinh-thuc")
    if "--khong-cong-dvc" not in sys.argv:
        _sync_cong_dvc(conn, run_at, ghi, tin_may_chu=True)
    else:
        _bo_qua(ghi, ["cong_dvc_quoc_gia"], "--khong-cong-dvc")
    if "--khong-phaplyvn" not in sys.argv:
        _sync_phaplyvn(ghi)
    else:
        _bo_qua(ghi, ["phaplyvn"], "--khong-phaplyvn")
    if "--khong-catp" not in sys.argv:
        _sync_congan_tin(conn, run_at, ghi)
    else:
        _bo_qua(ghi, ["congan_tin"], "--khong-catp")
    # Xuất dữ liệu trước khi đọc vbpl.vn: bước vbpl chậm không được làm chậm việc công bố dữ liệu mới.
    # Nếu tiến trình bị dừng giữa chừng, bản xuất này vẫn được lưu (workflow luôn chạy bước lưu dữ liệu).
    export.write_outputs(conn, DOCS_DATA_DIR, OVERRIDES_PATH, EXTRA_PATH, run_at)
    if "--khong-vbpl" not in sys.argv:
        _sync_vbpl(conn, run_at, ghi, kiem_tra_may_chu=True)
    else:
        _bo_qua(ghi, ["vbpl"], "--khong-vbpl")
    # Xuất lần hai để tình trạng vbpl.vn vừa đọc được đưa vào dữ liệu.
    export.write_outputs(conn, DOCS_DATA_DIR, OVERRIDES_PATH, EXTRA_PATH, run_at)

    label = "lần đầu, ghi nhận nền" if first_run else f"{change_count} thay đổi"
    print(f"Xong. Văn bản: {len(van_ban)}, thủ tục: {len(tthc)}. {label}.")
    return 0


def _bo_qua(ghi, nguon_list, tham_so):
    for nguon in nguon_list:
        ghi.ghi(nguon, BO_QUA, f"bỏ qua theo tham số {tham_so}")


def _cac_giai_doan():
    """Các giai đoạn cần cập nhật: mặc định cả ba giai đoạn (1: thủ tục và cư trú; 2: các lĩnh vực còn lại;
    3: đăng ký khác với công an). Chọn một giai đoạn bằng --giai-doan=1, 2 hoặc 3."""
    for arg in sys.argv:
        if arg.startswith("--giai-doan="):
            return [int(arg.split("=", 1)[1])]
    return [1, 2, 3]


def _sync_chinh_thuc(conn, run_at, giai_doan, ghi):
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
            ghi.ghi(nguon, OK, f"giai đoạn {giai_doan}: {len(found['items'])} văn bản liên quan, {new} mới")
        except BlockedError as error:
            conn.rollback()
            print(f"Nguồn {nguon} từ chối truy cập: {error}. Bỏ qua lần này.")
            ghi.ghi(nguon, BI_CHAN, f"giai đoạn {giai_doan}: {error}")
        except Exception as error:  # noqa: BLE001 - lỗi một nguồn không làm hỏng các nguồn khác
            conn.rollback()
            print(f"Nguồn {nguon} lỗi: {error}. Giữ dữ liệu cũ.")
            ghi.ghi(nguon, LOI, f"giai đoạn {giai_doan}: {error}")


def _chinh_thuc_trong_pham_vi(conn):
    """Văn bản chính thức đã lưu, bỏ thủ tục của ngành khác (không do công an). Dùng cho toàn văn và đối chiếu vbpl."""
    tu_khoa = nguon_chinh_thuc.tu_khoa_giai_doan(3, vbpl_sync.load_config()["tu_khoa_tim_van_ban_moi"])
    return nguon_chinh_thuc.loc_pham_vi(store.load_chinh_thuc(conn), tu_khoa)


def _sync_nguon_text(conn, ghi):
    """Toàn văn của văn bản nguồn chính thức (PDF). Lỗi ở đây không chặn cập nhật dữ liệu."""
    try:
        done, failed = nguon_text.sync_nguon_text(
            conn, nguon_chinh_thuc.Fetcher(), DOCS_DATA_DIR / "nguon_text", _chinh_thuc_trong_pham_vi(conn)
        )
        print(f"Toàn văn nguồn chính thức: thêm {done}, không đọc được {failed}.")
        ghi.ghi("toan_van", OK, f"thêm {done} văn bản, không đọc được {failed}")
    except BlockedError as error:
        print(f"Toàn văn nguồn chính thức bị từ chối: {error}. Thử lại lần sau.")
        ghi.ghi("toan_van", BI_CHAN, str(error))
    except Exception as error:  # noqa: BLE001
        print(f"Toàn văn nguồn chính thức lỗi: {error}. Giữ dữ liệu cũ.")
        ghi.ghi("toan_van", LOI, str(error))


def _sync_phaplyvn(ghi):
    """Văn bản mới từ vanban.phaplyvn.com (nguồn thứ cấp). Lỗi ở đây không làm lần chạy báo lỗi."""
    keywords = vbpl_sync.load_config()["tu_khoa_tim_van_ban_moi"]
    try:
        done, failed, moi = nguon_phaplyvn.dong_bo(nguon_chinh_thuc.Fetcher(delay_seconds=2.0), DOCS_DATA_DIR / "nguon_text", keywords)
        print(f"vanban.phaplyvn.com: {moi} đường dẫn mới; {done} có toàn văn; {failed} không đọc được.")
        ghi.ghi("phaplyvn", OK, f"{moi} văn bản mới liên quan; {done} có toàn văn; {failed} không đọc được")
    except BlockedError as error:
        print(f"vanban.phaplyvn.com từ chối truy cập: {error}")
        ghi.ghi("phaplyvn", BI_CHAN, str(error))
    except Exception as error:  # noqa: BLE001 - nguồn thứ cấp không làm hỏng các nguồn khác
        print(f"vanban.phaplyvn.com lỗi: {error}")
        ghi.ghi("phaplyvn", LOI, str(error))


def _sync_cong_dvc(conn, run_at, ghi, tin_may_chu=False):
    """Thủ tục do công an từ Cổng Dịch vụ công Quốc gia. Lỗi ở đây không chặn các nguồn khác.

    tin_may_chu: bật trên CI. Nếu server-chat đã đồng bộ hôm nay thì CI bỏ qua (cổng chặn GitHub, chỉ tốn thời gian).
    """
    run_date = datetime.fromisoformat(run_at).date()
    if tin_may_chu and cong_dvc.may_chu_da_dong_bo(conn, run_date):
        ghi.ghi("cong_dvc_quoc_gia", OK, "đồng bộ trên server-chat hôm nay")
        return
    try:
        tong, chon, moi = cong_dvc.dong_bo(conn, run_at)
        print(f"Cổng quốc gia: {tong} thủ tục công khai; chọn {chon} thủ tục có công an; {moi} thay đổi.")
        ghi.ghi("cong_dvc_quoc_gia", OK, f"{tong} thủ tục công khai, chọn {chon} có công an, {moi} thay đổi")
    except BlockedError as error:
        conn.rollback()
        print(f"Cổng quốc gia từ chối truy cập: {error}. Giữ dữ liệu cũ.")
        ghi.ghi("cong_dvc_quoc_gia", BI_CHAN, str(error))
    except Exception as error:  # noqa: BLE001 - lỗi một nguồn không làm hỏng các nguồn khác
        conn.rollback()
        print(f"Cổng quốc gia lỗi: {error}. Giữ dữ liệu cũ.")
        ghi.ghi("cong_dvc_quoc_gia", LOI, str(error))


def _sync_congan_tin(conn, run_at, ghi):
    """Tin nêu chỉ đạo, triển khai trên cổng Công an TP.HCM. Lỗi ở đây không chặn các nguồn khác."""
    try:
        ket_qua = nguon_catp.doc_tin(nguon_chinh_thuc.Fetcher(), nguon_catp.load_config())
        moi = store.sync_tin_catp(conn, ket_qua["chi_dao"], run_at)
        conn.commit()
        print(f"Tin Công an TP.HCM: {ket_qua['tong']} tin đọc được, {len(ket_qua['chi_dao'])} có chỉ đạo, {moi} mới.")
        ghi.ghi("congan_tin", OK, f"{ket_qua['tong']} tin đọc được, {len(ket_qua['chi_dao'])} có chỉ đạo, {moi} mới")
    except BlockedError as error:
        conn.rollback()
        print(f"Tin Công an TP.HCM từ chối truy cập: {error}. Giữ dữ liệu cũ.")
        ghi.ghi("congan_tin", BI_CHAN, str(error))
    except Exception as error:  # noqa: BLE001 - lỗi một nguồn không làm hỏng các nguồn khác
        conn.rollback()
        print(f"Tin Công an TP.HCM lỗi: {error}. Giữ dữ liệu cũ.")
        ghi.ghi("congan_tin", LOI, str(error))


def _sync_vbpl(conn, run_at, ghi, kiem_tra_may_chu=False):
    """Đọc trạng thái từ vbpl.vn. Lỗi ở bước này không chặn cập nhật từ cổng Phòng CSQLHC.

    kiem_tra_may_chu: chỉ bật trên CI (GitHub Actions). CI báo lỗi nếu server-chat không đọc hôm nay.
    Server-chat không bật, vì chính nó ghi dấu hiệu sau khi đọc xong.
    """
    try:
        config = vbpl_sync.load_config()
        extra_numbers = [item["so_ky_hieu"] for item in json.loads(EXTRA_PATH.read_text(encoding="utf-8"))]
        extra_numbers += [row["so_ky_hieu"] for row in _chinh_thuc_trong_pham_vi(conn)]
        run_date = datetime.fromisoformat(run_at).date()
        so_doc, so_loi, loi_tim, so_khong_con = vbpl_sync.sync(conn, extra_numbers, run_at, run_date, config)
        conn.commit()
        thong_bao = (
            f"đọc trạng thái {so_doc} văn bản, {so_loi} không đọc được, "
            f"{so_khong_con} không còn trên vbpl.vn (liên kết cũ)"
        )
        print(f"vbpl.vn: {thong_bao}.")
        if loi_tim:
            ghi.ghi("vbpl", LOI, f"không tìm được văn bản mới ({loi_tim}); {thong_bao}")
        elif so_doc and so_loi * 2 > so_doc:
            # Quá nửa số văn bản không đọc được thì báo lỗi, không báo "ok" như trước.
            ghi.ghi("vbpl", LOI, f"quá nửa số văn bản không đọc được: {thong_bao}")
        else:
            ghi.ghi("vbpl", OK, thong_bao)
        if kiem_tra_may_chu and not vbpl_sync.may_chu_da_doc(conn, run_date):
            # server-chat không đọc được hôm nay (tác vụ tchc-vbpl-kham-pha lỗi hoặc chưa chạy): báo để kiểm tra.
            # Trạng thái LOI không bị hạ xuống OK bởi các bước khác trong cùng lần chạy.
            ghi.ghi("vbpl", LOI, "server-chat chưa đọc trạng thái và toàn văn hôm nay; kiểm tra tác vụ tchc-vbpl-kham-pha")
        if vbpl_sync.may_chu_da_doc(conn, run_date):
            # server-chat đã đọc trạng thái và toàn văn hôm nay: không mở vbpl.vn từ GitHub (đang bị chặn).
            print("vbpl.vn: server-chat đã đọc trạng thái và toàn văn, bỏ qua bước toàn văn ở đây.")
        else:
            texts = vbpl_text.sync_texts(conn, DOCS_DATA_DIR / "vbpl_text", config["do_tre_giua_cac_yeu_cau_giay"])
            print(f"vbpl.vn: đã lưu toàn văn {texts} văn bản có thay đổi.")
    except ImportError as error:
        conn.rollback()
        print(f"Bỏ qua vbpl.vn: thiếu thư viện ({error}). Cài Playwright để bật bước này.")
        ghi.ghi("vbpl", LOI, f"thiếu thư viện ({error})")
    except BlockedError as error:
        conn.commit()
        print(f"vbpl.vn chặn truy cập: {error}. Giữ dữ liệu cũ, không thử lại.")
        ghi.ghi("vbpl", BI_CHAN, str(error))
    except Exception as error:  # noqa: BLE001 - lỗi vbpl không làm hỏng dữ liệu của cổng
        conn.commit()
        print(f"vbpl.vn lỗi: {error}. Giữ dữ liệu cũ.")
        ghi.ghi("vbpl", LOI, str(error))


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
