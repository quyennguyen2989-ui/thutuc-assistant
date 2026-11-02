"""Lưu trữ SQLite và phát hiện thay đổi giữa hai lần chạy.

Mỗi bản ghi được băm (SHA-256) trên nội dung đã chuẩn hóa. Khi băm khác với lần trước,
ghi lại các trường thay đổi. Bản ghi biến mất khỏi cổng được đánh dấu, không xóa.
"""

import json
import sqlite3

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
"""


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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
                "ngay_hieu_luc", "ngay_cap_nhat", "kiem_tra_luc", "loi"]


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
