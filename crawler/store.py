"""Lưu trữ SQLite và phát hiện thay đổi giữa hai lần chạy.

Mỗi bản ghi được băm (SHA-256) trên nội dung đã chuẩn hóa. Khi băm khác với lần trước,
ghi lại các trường thay đổi. Bản ghi biến mất khỏi cổng được đánh dấu, không xóa.
"""

import json
import sqlite3
import zlib

from .normalize import content_hash, diff_fields

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    kind TEXT NOT NULL,
    id INTEGER NOT NULL,
    data TEXT NOT NULL,
    hash TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    missing INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    change_type TEXT NOT NULL,
    diff TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_at TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    van_ban_count INTEGER NOT NULL DEFAULT 0,
    tthc_count INTEGER NOT NULL DEFAULT 0,
    change_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS vbpl (
    url TEXT PRIMARY KEY,
    so_ky_hieu TEXT,
    sheet INTEGER,
    lastmod TEXT,
    tieu_de TEXT,
    tinh_trang TEXT,
    ngay_hieu_luc TEXT,
    ngay_cap_nhat TEXT,
    kiem_tra_luc TEXT,
    loi TEXT
);
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nguon_chinh_thuc (
    nguon TEXT NOT NULL,
    url TEXT NOT NULL,
    so_ky_hieu TEXT NOT NULL,
    loai TEXT,
    trich_yeu TEXT,
    co_quan_ban_hanh TEXT,
    ngay_ban_hanh TEXT,
    ngay_hieu_luc TEXT,
    first_seen TEXT NOT NULL,
    giai_doan INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (nguon, url)
);
CREATE TABLE IF NOT EXISTS tin_catp (
    url TEXT PRIMARY KEY,
    tieu_de TEXT NOT NULL,
    ngay_dang TEXT NOT NULL,
    muc TEXT NOT NULL,
    tom_tat TEXT NOT NULL DEFAULT '',
    tu_khoa TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nguon_run (
    run_at TEXT NOT NULL,
    nguon TEXT NOT NULL,
    trang_thai TEXT NOT NULL,
    thong_bao TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_at, nguon)
);
"""


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Cơ sở dữ liệu cũ chưa có cột lịch sử sửa đổi của vbpl.vn.
    vbpl_columns = {row["name"] for row in conn.execute("PRAGMA table_info(vbpl)")}
    if "lich_su" not in vbpl_columns:
        conn.execute("ALTER TABLE vbpl ADD COLUMN lich_su TEXT")
    # Cơ sở dữ liệu cũ chưa có cột giai đoạn của nguồn chính thức.
    chinh_thuc_columns = {row["name"] for row in conn.execute("PRAGMA table_info(nguon_chinh_thuc)")}
    if "giai_doan" not in chinh_thuc_columns:
        conn.execute("ALTER TABLE nguon_chinh_thuc ADD COLUMN giai_doan INTEGER NOT NULL DEFAULT 1")
    return conn


def is_first_run(conn):
    row = conn.execute("SELECT COUNT(*) AS n FROM runs WHERE status = 'ok'").fetchone()
    return row["n"] == 0


def active_count(conn, kind):
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM records WHERE kind = ? AND missing = 0", (kind,)
    ).fetchone()
    return row["n"]


def sync_records(conn, kind, records, run_at, first_run):
    """Đồng bộ danh sách bản ghi mới vào DB. Trả về số thay đổi được ghi nhận."""
    existing = {
        row["id"]: row
        for row in conn.execute("SELECT * FROM records WHERE kind = ?", (kind,))
    }
    seen_ids = set()
    change_count = 0

    for record in records:
        record_id = record["id"]
        seen_ids.add(record_id)
        new_hash = content_hash(record)
        row = existing.get(record_id)

        if row is None:
            conn.execute(
                "INSERT INTO records (kind, id, data, hash, first_seen, last_seen) VALUES (?, ?, ?, ?, ?, ?)",
                (kind, record_id, json.dumps(record, ensure_ascii=False), new_hash, run_at, run_at),
            )
            if not first_run:
                _log_change(conn, run_at, kind, record_id, "moi", {})
                change_count += 1
            continue

        if row["hash"] != new_hash:
            old_record = json.loads(row["data"])
            conn.execute(
                "UPDATE records SET data = ?, hash = ?, last_seen = ?, missing = 0 WHERE kind = ? AND id = ?",
                (json.dumps(record, ensure_ascii=False), new_hash, run_at, kind, record_id),
            )
            if not first_run:
                _log_change(conn, run_at, kind, record_id, "thay_doi", diff_fields(old_record, record))
                change_count += 1
        else:
            if row["missing"]:
                if not first_run:
                    _log_change(conn, run_at, kind, record_id, "quay_lai", {})
                    change_count += 1
            conn.execute(
                "UPDATE records SET last_seen = ?, missing = 0 WHERE kind = ? AND id = ?",
                (run_at, kind, record_id),
            )

    for record_id, row in existing.items():
        if record_id not in seen_ids and not row["missing"]:
            conn.execute(
                "UPDATE records SET missing = 1 WHERE kind = ? AND id = ?", (kind, record_id)
            )
            if not first_run:
                _log_change(conn, run_at, kind, record_id, "khong_con_tren_cong", {})
                change_count += 1

    return change_count


def _log_change(conn, run_at, kind, record_id, change_type, diff):
    conn.execute(
        "INSERT INTO changes (run_at, kind, record_id, change_type, diff) VALUES (?, ?, ?, ?, ?)",
        (run_at, kind, record_id, change_type, json.dumps(diff, ensure_ascii=False)),
    )


def record_change(conn, run_at, kind, record_id, change_type, diff):
    """Ghi một thay đổi (kể cả của vbpl.vn) vào nhật ký cập nhật."""
    _log_change(conn, run_at, kind, record_id, change_type, diff)


def log_run(conn, run_at, status, van_ban_count, tthc_count, change_count):
    conn.execute(
        "INSERT OR REPLACE INTO runs (run_at, status, van_ban_count, tthc_count, change_count) VALUES (?, ?, ?, ?, ?)",
        (run_at, status, van_ban_count, tthc_count, change_count),
    )


def sync_tin_catp(conn, items, run_at):
    """Ghi các tin chỉ đạo của Công an TP.HCM. Tin đã có thì chỉ cập nhật lần thấy gần nhất. Trả về số tin mới."""
    new = 0
    for item in items:
        if conn.execute("SELECT 1 FROM tin_catp WHERE url = ?", (item["url"],)).fetchone():
            conn.execute("UPDATE tin_catp SET last_seen = ? WHERE url = ?", (run_at, item["url"]))
            continue
        conn.execute(
            "INSERT INTO tin_catp (url, tieu_de, ngay_dang, muc, tom_tat, tu_khoa, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item["url"], item["tieu_de"], item["ngay_dang"], item["muc"], item.get("tom_tat", ""),
             json.dumps(item.get("tu_khoa", []), ensure_ascii=False), run_at, run_at),
        )
        new += 1
    return new


def load_tin_catp(conn, limit=300):
    """Tin chỉ đạo mới nhất trước, theo ngày đăng."""
    rows = conn.execute(
        "SELECT url, tieu_de, ngay_dang, muc, tom_tat, tu_khoa, first_seen FROM tin_catp"
        " ORDER BY ngay_dang DESC, url LIMIT ?",
        (limit,),
    )
    return [{**dict(row), "tu_khoa": json.loads(row["tu_khoa"])} for row in rows]


def log_nguon(conn, run_at, nguon, trang_thai, thong_bao):
    """Trạng thái một nguồn trong một lần chạy. Ghi lại cùng khóa thì thay thế."""
    conn.execute(
        "INSERT OR REPLACE INTO nguon_run (run_at, nguon, trang_thai, thong_bao) VALUES (?, ?, ?, ?)",
        (run_at, nguon, trang_thai, thong_bao),
    )


def load_nguon_status(conn):
    """Với mỗi nguồn: trạng thái của lần chạy gần nhất, và lần chạy thành công gần nhất (nếu có)."""
    status = {}
    latest = conn.execute(
        "SELECT r.nguon, r.run_at, r.trang_thai, r.thong_bao FROM nguon_run r"
        " JOIN (SELECT nguon, MAX(run_at) AS run_at FROM nguon_run GROUP BY nguon) m"
        " ON r.nguon = m.nguon AND r.run_at = m.run_at"
    )
    for row in latest:
        status[row["nguon"]] = {
            "luc": row["run_at"],
            "trang_thai": row["trang_thai"],
            "thong_bao": row["thong_bao"],
            "thanh_cong_gan_nhat": None,
        }
    for row in conn.execute(
        "SELECT nguon, MAX(run_at) AS run_at FROM nguon_run WHERE trang_thai = 'ok' GROUP BY nguon"
    ):
        status.setdefault(row["nguon"], {})["thanh_cong_gan_nhat"] = row["run_at"]
    return status


def load_records(conn, kind):
    """Trả về các bản ghi đang có trên cổng (không gồm bản ghi đã biến mất)."""
    rows = conn.execute(
        "SELECT data, missing, first_seen, last_seen FROM records WHERE kind = ? ORDER BY id",
        (kind,),
    )
    result = []
    for row in rows:
        record = json.loads(row["data"])
        record["_missing"] = bool(row["missing"])
        record["_first_seen"] = row["first_seen"]
        record["_last_seen"] = row["last_seen"]
        result.append(record)
    return result


VBPL_COLUMNS = ["url", "so_ky_hieu", "sheet", "lastmod", "tieu_de", "tinh_trang",
                "ngay_hieu_luc", "ngay_cap_nhat", "kiem_tra_luc", "loi", "lich_su"]


def upsert_vbpl(conn, row):
    """Ghi các cột có trong row cho một văn bản vbpl.vn. Cột không có trong row giữ nguyên."""
    columns = [column for column in VBPL_COLUMNS if column in row]
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{column} = excluded.{column}" for column in columns if column != "url")
    sql = f"INSERT INTO vbpl ({', '.join(columns)}) VALUES ({placeholders})"
    if updates:
        sql += f" ON CONFLICT(url) DO UPDATE SET {updates}"
    else:
        sql += " ON CONFLICT(url) DO NOTHING"
    conn.execute(sql, [row[column] for column in columns])


def load_vbpl(conn):
    return [dict(row) for row in conn.execute("SELECT * FROM vbpl ORDER BY so_ky_hieu, url")]


def get_state(conn, key, default=None):
    row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn, key, value):
    conn.execute(
        "INSERT INTO state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def load_chinh_thuc(conn, nguon=None):
    """Văn bản đã đọc từ các nguồn chính thức (có thể lọc theo một nguồn)."""
    if nguon:
        rows = conn.execute(
            "SELECT * FROM nguon_chinh_thuc WHERE nguon = ? ORDER BY ngay_ban_hanh DESC, url", (nguon,)
        )
    else:
        rows = conn.execute("SELECT * FROM nguon_chinh_thuc ORDER BY ngay_ban_hanh DESC, url")
    return [dict(row) for row in rows]


CAC_TRUONG_CHINH_THUC = ("so_ky_hieu", "loai", "trich_yeu", "co_quan_ban_hanh", "ngay_ban_hanh", "ngay_hieu_luc")


def _cap_nhat_chinh_thuc(conn, run_at, nguon, row, item, first_time):
    """Văn bản đã có: điền các trường còn trống, sửa trường khác giá trị mới từ nguồn chính thức.

    Mỗi chỗ khác giá trị được ghi vào nhật ký (trừ lần nạp đầu), để việc sửa dữ liệu có thể kiểm tra lại.
    """
    diff = {}
    for field in CAC_TRUONG_CHINH_THUC:
        moi = item.get(field) or ""
        cu = row[field] or ""
        if moi and moi != cu:
            diff[field] = {"cu": cu or None, "moi": moi}
    if not diff:
        return
    assignments = ", ".join(f"{field} = ?" for field in diff)
    conn.execute(
        f"UPDATE nguon_chinh_thuc SET {assignments} WHERE nguon = ? AND url = ?",
        [value["moi"] for value in diff.values()] + [nguon, item["url"]],
    )
    if not first_time:
        name = f"{row['so_ky_hieu']}: {row['trich_yeu'] or ''}".strip(": ")
        _log_change(conn, run_at, "chinh_thuc", zlib.crc32(item["url"].encode("utf-8")), "thay_doi",
                    {"_ten": name[:200], "_nguon": nguon, **diff})


def sync_chinh_thuc(conn, nguon, items, run_at, giai_doan=1):
    """Ghi văn bản của một nguồn. Lần đầu của nguồn trong một giai đoạn chỉ ghi nền; các lần sau ghi nhận văn bản mới.

    Văn bản đã có (cùng nguồn và đường dẫn) không ghi lại, nên không trùng. Trả về số văn bản mới được ghi nhận.
    """
    baseline_key = f"chinh_thuc_nen:{nguon}:{giai_doan}"
    first_time = get_state(conn, baseline_key) is None
    new_count = 0
    for item in items:
        row = conn.execute(
            "SELECT * FROM nguon_chinh_thuc WHERE nguon = ? AND url = ?", (nguon, item["url"])
        ).fetchone()
        if row:
            _cap_nhat_chinh_thuc(conn, run_at, nguon, row, item, first_time)
            continue
        conn.execute(
            "INSERT INTO nguon_chinh_thuc (nguon, url, so_ky_hieu, loai, trich_yeu, co_quan_ban_hanh,"
            " ngay_ban_hanh, ngay_hieu_luc, first_seen, giai_doan) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (nguon, item["url"], item["so_ky_hieu"], item.get("loai", ""), item.get("trich_yeu", ""),
             item.get("co_quan_ban_hanh", ""), item.get("ngay_ban_hanh", ""),
             item.get("ngay_hieu_luc", ""), run_at, giai_doan),
        )
        if not first_time:
            name = f"{item['so_ky_hieu']}: {item.get('trich_yeu', '')}".strip(": ")
            diff = {"_ten": name[:200], "_nguon": nguon}
            _log_change(conn, run_at, "chinh_thuc", zlib.crc32(item["url"].encode("utf-8")), "moi", diff)
            new_count += 1
    set_state(conn, baseline_key, run_at)
    return new_count


def last_change_dates(conn, kind):
    """Ngày ghi nhận thay đổi nội dung gần nhất của từng bản ghi (theo mã bản ghi).

    Không tính lần ghi nền đầu tiên, vì khi đó chưa có thay đổi nào được phát hiện.
    """
    rows = conn.execute(
        "SELECT record_id, MAX(run_at) AS run_at FROM changes"
        " WHERE kind = ? AND change_type IN ('thay_doi', 'moi', 'quay_lai') GROUP BY record_id",
        (kind,),
    )
    return {row["record_id"]: row["run_at"] for row in rows}


def load_changes(conn, limit=200):
    rows = conn.execute(
        "SELECT run_at, kind, record_id, change_type, diff FROM changes ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return [
        {
            "run_at": row["run_at"],
            "kind": row["kind"],
            "record_id": row["record_id"],
            "change_type": row["change_type"],
            "diff": json.loads(row["diff"]),
        }
        for row in rows
    ]
