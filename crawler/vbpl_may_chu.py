"""Đọc trạng thái và toàn văn vbpl.vn trên server-chat, rồi đẩy kết quả lên repo. Chạy hằng ngày, trước CI.

Lý do: GitHub Actions bị vbpl.vn chặn trang chi tiết (HTTP 403), còn server-chat đọc được bằng Chromium
(Playwright). Luồng chạy:
1. Tải cơ sở dữ liệu và chỉ mục toàn văn từ nhánh main của repo.
2. Chạy đúng phần vbpl của crawler.update (_sync_vbpl): nạp văn bản tìm được, đọc trạng thái, lưu toàn văn.
3. Đồng bộ thủ tục Cổng Dịch vụ công quốc gia (_sync_cong_dvc), vì server-chat vào được cổng còn GitHub thì không.
4. Nếu có thay đổi, đẩy cơ sở dữ liệu, chỉ mục và các tệp toàn văn mới trong MỘT commit.

Khi đó CI hằng ngày chỉ xuất dữ liệu: vbpl và Cổng quốc gia đã có dữ liệu hôm nay, nên không cần mở các trang đó.

Cách chạy (từ thư mục repo, nơi có thư mục crawler):
    python -m crawler.vbpl_may_chu --day-github <tệp token>

Mã thoát: 0 xong; 1 lỗi không mong đợi; 2 không tải được dữ liệu từ repo; 3 vbpl.vn lỗi hoặc bị chặn.
Khi lỗi, không đẩy gì lên repo.
"""

import argparse
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import cong_dvc, kham_pha_github, nguon_trang_thai, store, update, vbpl_sync
from .client import USER_AGENT

RAW = "https://raw.githubusercontent.com/quyennguyen2989-ui/thutuc-assistant/main/"
DB_REL = "data/thutuc.db"
INDEX_REL = "docs/data/vbpl_text/index.json"
TEXT_REL = "docs/data/vbpl_text"
GIO_VIET_NAM = timezone(timedelta(hours=7))


class LoiTaiVe(RuntimeError):
    pass


def tai_ve(duong_dan_tuong_doi):
    """Tải một tệp từ nhánh main qua raw.githubusercontent.com (không cần token)."""
    request = urllib.request.Request(RAW + duong_dan_tuong_doi, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except OSError as error:
        raise LoiTaiVe(f"không tải được {duong_dan_tuong_doi}: {error}") from error


def anh_chup_thu_muc(thu_muc, goc):
    """{đường dẫn tương đối (dấu /): mã blob} của mọi tệp trong thư mục."""
    thu_muc = Path(thu_muc)
    if not thu_muc.exists():
        return {}
    anh = {}
    for tep in thu_muc.rglob("*"):
        if tep.is_file():
            rel = tep.relative_to(goc).as_posix()
            anh[rel] = kham_pha_github.blob_sha(tep.read_bytes())
    return anh


def chay(goc, token_path=None, bay_gio=None):
    """Chạy một lượt. Trả về mã thoát."""
    goc = Path(goc)
    run_at = (bay_gio or datetime.now(GIO_VIET_NAM)).isoformat(timespec="seconds")

    db_bytes = tai_ve(DB_REL)
    index_bytes = tai_ve(INDEX_REL)
    db_path = goc / DB_REL
    index_path = goc / INDEX_REL
    db_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_bytes(db_bytes)
    index_path.write_bytes(index_bytes)
    # Mã blob lúc tải về: dùng để phát hiện nếu CI ghi đè trên GitHub trong lúc chạy.
    sha_cu = {DB_REL: kham_pha_github.blob_sha(db_bytes), INDEX_REL: kham_pha_github.blob_sha(index_bytes)}
    truoc = anh_chup_thu_muc(goc / TEXT_REL, goc)

    conn = store.connect(db_path)
    ghi = nguon_trang_thai.Ghi(conn, run_at)
    try:
        update._sync_vbpl(conn, run_at, ghi)
        trang_thai = ghi.ket_qua.get("vbpl", {}).get("trang_thai")
        if trang_thai == nguon_trang_thai.OK:
            # Đánh dấu để CI biết hôm nay đã có trạng thái và toàn văn từ server-chat.
            store.set_state(conn, vbpl_sync.MAY_CHU_STATE, run_at[:10])
        conn.commit()
        # Cổng Dịch vụ công quốc gia: server-chat vào được, GitHub thì bị timeout. Lỗi ở đây không làm hỏng vbpl.
        update._sync_cong_dvc(conn, run_at, ghi)
        if ghi.ket_qua.get("cong_dvc_quoc_gia", {}).get("trang_thai") == nguon_trang_thai.OK:
            store.set_state(conn, cong_dvc.MAY_CHU_STATE, run_at[:10])
        conn.commit()
    finally:
        conn.close()

    tep = {}
    sau = anh_chup_thu_muc(goc / TEXT_REL, goc)
    for rel, ma in sau.items():
        if truoc.get(rel) != ma:
            tep[rel] = (goc / rel).read_bytes()
    if index_path.read_bytes() != index_bytes:
        tep[INDEX_REL] = index_path.read_bytes()
    db_moi = db_path.read_bytes()
    if kham_pha_github.blob_sha(db_moi) != sha_cu[DB_REL]:
        tep[DB_REL] = db_moi

    print(f"vbpl.vn: trạng thái {trang_thai}; {len(tep)} tệp thay đổi (gồm cơ sở dữ liệu nếu có).")
    if token_path and tep:
        thong_diep = f"Cập nhật trạng thái vbpl.vn trên server-chat ({run_at[:10]})"
        token = kham_pha_github.doc_token(token_path)
        so_tep = kham_pha_github.day_nhieu_tep(token, tep, thong_diep, sha_cu={
            DB_REL: sha_cu[DB_REL], INDEX_REL: sha_cu[INDEX_REL],
        })
        print(f"Đã đẩy {so_tep} tệp lên GitHub trong một commit.")
    elif not token_path:
        print("Không có --day-github: không đẩy gì lên GitHub.")

    return 0 if trang_thai == nguon_trang_thai.OK else 3


def main(argv=None):
    parser = argparse.ArgumentParser(description="Đọc vbpl.vn trên server-chat rồi đẩy kết quả lên repo.")
    parser.add_argument("--goc", default=str(Path(__file__).resolve().parent.parent), help="thư mục repo")
    parser.add_argument("--day-github", help="tệp chứa token GitHub; có thì đẩy kết quả lên repo")
    args = parser.parse_args(argv)
    try:
        return chay(args.goc, args.day_github)
    except LoiTaiVe as error:
        print(f"Không chạy được: {error}. Không đẩy gì.", file=sys.stderr)
        return 2
    except kham_pha_github.LoiGitHub as error:
        print(f"Không đẩy được lên GitHub: {error}.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
