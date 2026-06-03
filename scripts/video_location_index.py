#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys


SCHEMA = """
CREATE TABLE IF NOT EXISTS video_object (
    video_id TEXT PRIMARY KEY,
    active_tier TEXT CHECK(active_tier IN ('ssd', 'hdd')),
    hot_endpoint_name TEXT,
    hot_endpoint TEXT,
    hot_bucket TEXT,
    hot_key TEXT,
    hot_present INTEGER NOT NULL DEFAULT 0,
    cold_endpoint_name TEXT,
    cold_endpoint TEXT,
    cold_bucket TEXT,
    cold_key TEXT,
    cold_present INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER,
    status TEXT NOT NULL DEFAULT 'created',
    push_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT,
    last_push_at TEXT
);

CREATE TABLE IF NOT EXISTS video_location_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    event TEXT NOT NULL,
    tier TEXT,
    endpoint_name TEXT,
    bucket TEXT,
    object_key TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_video_object_active_tier
ON video_object(active_tier);

CREATE INDEX IF NOT EXISTS idx_video_location_history_video_id
ON video_location_history(video_id);
"""


def now_utc():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path):
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def add_history(conn, video_id, event, tier=None, endpoint_name=None, bucket=None, object_key=None, note=None):
    conn.execute(
        """
        INSERT INTO video_location_history
        (video_id, event, tier, endpoint_name, bucket, object_key, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (video_id, event, tier, endpoint_name, bucket, object_key, note, now_utc()),
    )


def ensure_row(conn, video_id, size_bytes=None):
    timestamp = now_utc()
    conn.execute(
        """
        INSERT OR IGNORE INTO video_object
        (video_id, size_bytes, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (video_id, size_bytes, timestamp, timestamp),
    )
    if size_bytes is not None:
        conn.execute(
            "UPDATE video_object SET size_bytes = ?, updated_at = ? WHERE video_id = ?",
            (size_bytes, timestamp, video_id),
        )


def set_hot(conn, args):
    ensure_row(conn, args.video_id, args.size_bytes)
    timestamp = now_utc()
    conn.execute(
        """
        UPDATE video_object
        SET active_tier = 'ssd',
            hot_endpoint_name = ?,
            hot_endpoint = ?,
            hot_bucket = ?,
            hot_key = ?,
            hot_present = 1,
            status = 'hot_ready',
            updated_at = ?
        WHERE video_id = ?
        """,
        (args.endpoint_name, args.endpoint, args.bucket, args.key, timestamp, args.video_id),
    )
    add_history(conn, args.video_id, "set_hot", "ssd", args.endpoint_name, args.bucket, args.key, args.note)
    conn.commit()


def set_cold(conn, args):
    ensure_row(conn, args.video_id, args.size_bytes)
    row = conn.execute("SELECT active_tier, hot_present FROM video_object WHERE video_id = ?", (args.video_id,)).fetchone()
    make_active = args.make_active or not row["active_tier"] or not row["hot_present"]
    active_sql = "active_tier = 'hdd'," if make_active else ""
    timestamp = now_utc()
    conn.execute(
        """
        UPDATE video_object
        SET {active_sql}
            cold_endpoint_name = ?,
            cold_endpoint = ?,
            cold_bucket = ?,
            cold_key = ?,
            cold_present = 1,
            status = ?,
            archived_at = ?,
            updated_at = ?
        WHERE video_id = ?
        """.format(active_sql=active_sql),
        (
            args.endpoint_name,
            args.endpoint,
            args.bucket,
            args.key,
            "cold_active" if make_active else "archived",
            timestamp,
            timestamp,
            args.video_id,
        ),
    )
    add_history(conn, args.video_id, "set_cold", "hdd", args.endpoint_name, args.bucket, args.key, args.note)
    conn.commit()


def object_key(prefix, index):
    return "{prefix}{idx:06d}.bin".format(prefix=prefix, idx=index)


def cmd_register_range(args):
    conn = connect(args.db)
    setter = set_hot if args.tier == "ssd" else set_cold
    for index in range(args.start_index, args.start_index + args.count):
        video_id = "{prefix}{idx:06d}".format(prefix=args.video_prefix, idx=index)
        key = object_key(args.object_prefix, index)
        sub_args = argparse.Namespace(
            video_id=video_id,
            endpoint_name=args.endpoint_name,
            endpoint=args.endpoint,
            bucket=args.bucket,
            key=key,
            size_bytes=args.size_bytes,
            make_active=args.make_active,
            note=args.note,
        )
        setter(conn, sub_args)
    print(json.dumps({"registered": args.count, "tier": args.tier, "db": args.db}, sort_keys=True))


def choose_location(row, prefer):
    if prefer == "active":
        order = [row["active_tier"], "ssd", "hdd"]
    elif prefer == "ssd":
        order = ["ssd", "hdd"]
    else:
        order = ["hdd", "ssd"]

    seen = set()
    for tier in order:
        if not tier or tier in seen:
            continue
        seen.add(tier)
        if tier == "ssd" and row["hot_present"]:
            return {
                "tier": "ssd",
                "endpoint_name": row["hot_endpoint_name"],
                "endpoint": row["hot_endpoint"],
                "bucket": row["hot_bucket"],
                "key": row["hot_key"],
            }
        if tier == "hdd" and row["cold_present"]:
            return {
                "tier": "hdd",
                "endpoint_name": row["cold_endpoint_name"],
                "endpoint": row["cold_endpoint"],
                "bucket": row["cold_bucket"],
                "key": row["cold_key"],
            }
    return None


def cmd_resolve(args):
    conn = connect(args.db)
    row = conn.execute("SELECT * FROM video_object WHERE video_id = ?", (args.video_id,)).fetchone()
    if not row:
        raise SystemExit("video_id not found: {0}".format(args.video_id))
    location = choose_location(row, args.prefer)
    if not location:
        raise SystemExit("no usable location for video_id: {0}".format(args.video_id))
    result = dict(location)
    result.update(
        {
            "video_id": args.video_id,
            "active_tier": row["active_tier"],
            "hot_present": bool(row["hot_present"]),
            "cold_present": bool(row["cold_present"]),
            "status": row["status"],
            "push_count": row["push_count"],
        }
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def cmd_evict_hot(args):
    conn = connect(args.db)
    row = conn.execute("SELECT cold_present FROM video_object WHERE video_id = ?", (args.video_id,)).fetchone()
    if not row:
        raise SystemExit("video_id not found: {0}".format(args.video_id))
    if not row["cold_present"]:
        raise SystemExit("cannot evict hot copy before cold copy exists: {0}".format(args.video_id))
    timestamp = now_utc()
    conn.execute(
        """
        UPDATE video_object
        SET hot_present = 0,
            active_tier = 'hdd',
            status = 'hot_evicted',
            updated_at = ?
        WHERE video_id = ?
        """,
        (timestamp, args.video_id),
    )
    add_history(conn, args.video_id, "evict_hot", "ssd", note=args.note)
    conn.commit()
    print(json.dumps({"evicted_hot": args.video_id}, sort_keys=True))


def cmd_record_push(args):
    conn = connect(args.db)
    timestamp = now_utc()
    cur = conn.execute(
        """
        UPDATE video_object
        SET push_count = push_count + 1,
            last_push_at = ?,
            updated_at = ?
        WHERE video_id = ?
        """,
        (timestamp, timestamp, args.video_id),
    )
    if cur.rowcount == 0:
        raise SystemExit("video_id not found: {0}".format(args.video_id))
    add_history(conn, args.video_id, "push_read", args.tier, note=args.note)
    conn.commit()
    print(json.dumps({"recorded_push": args.video_id}, sort_keys=True))


def cmd_list(args):
    conn = connect(args.db)
    rows = conn.execute(
        """
        SELECT video_id, active_tier, hot_present, cold_present, status, push_count,
               hot_endpoint_name, hot_bucket, hot_key,
               cold_endpoint_name, cold_bucket, cold_key,
               updated_at
        FROM video_object
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (args.limit,),
    ).fetchall()
    for row in rows:
        print(json.dumps(dict(row), ensure_ascii=False, sort_keys=True))


def cmd_reset(args):
    if not args.yes:
        raise SystemExit("refusing to reset without --yes")
    conn = connect(args.db)
    conn.execute("DELETE FROM video_location_history")
    conn.execute("DELETE FROM video_object")
    conn.commit()
    print(json.dumps({"reset": args.db}, sort_keys=True))


def cmd_init(args):
    conn = connect(args.db)
    conn.close()
    print(json.dumps({"initialized": args.db}, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser(description="VideoId to MinIO location index for dual-MinIO tests")
    parser.add_argument("--db", default=os.environ.get("VIDEO_LOCATION_DB", "video-location-index.sqlite3"))
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init")
    init.set_defaults(func=cmd_init)

    hot = sub.add_parser("set-hot")
    hot.add_argument("--video-id", required=True)
    hot.add_argument("--endpoint-name", required=True)
    hot.add_argument("--endpoint", required=True)
    hot.add_argument("--bucket", required=True)
    hot.add_argument("--key", required=True)
    hot.add_argument("--size-bytes", type=int)
    hot.add_argument("--note")
    hot.set_defaults(func=lambda args: set_hot(connect(args.db), args))

    cold = sub.add_parser("set-cold")
    cold.add_argument("--video-id", required=True)
    cold.add_argument("--endpoint-name", required=True)
    cold.add_argument("--endpoint", required=True)
    cold.add_argument("--bucket", required=True)
    cold.add_argument("--key", required=True)
    cold.add_argument("--size-bytes", type=int)
    cold.add_argument("--make-active", action="store_true")
    cold.add_argument("--note")
    cold.set_defaults(func=lambda args: set_cold(connect(args.db), args))

    register = sub.add_parser("register-range")
    register.add_argument("--tier", choices=["ssd", "hdd"], required=True)
    register.add_argument("--video-prefix", required=True)
    register.add_argument("--object-prefix", required=True)
    register.add_argument("--count", type=int, required=True)
    register.add_argument("--start-index", type=int, default=0)
    register.add_argument("--endpoint-name", required=True)
    register.add_argument("--endpoint", required=True)
    register.add_argument("--bucket", required=True)
    register.add_argument("--size-bytes", type=int)
    register.add_argument("--make-active", action="store_true")
    register.add_argument("--note")
    register.set_defaults(func=cmd_register_range)

    resolve = sub.add_parser("resolve")
    resolve.add_argument("--video-id", required=True)
    resolve.add_argument("--prefer", choices=["active", "ssd", "hdd"], default="ssd")
    resolve.set_defaults(func=cmd_resolve)

    evict = sub.add_parser("evict-hot")
    evict.add_argument("--video-id", required=True)
    evict.add_argument("--note")
    evict.set_defaults(func=cmd_evict_hot)

    push = sub.add_parser("record-push")
    push.add_argument("--video-id", required=True)
    push.add_argument("--tier", choices=["ssd", "hdd"])
    push.add_argument("--note")
    push.set_defaults(func=cmd_record_push)

    list_cmd = sub.add_parser("list")
    list_cmd.add_argument("--limit", type=int, default=20)
    list_cmd.set_defaults(func=cmd_list)

    reset = sub.add_parser("reset")
    reset.add_argument("--yes", action="store_true")
    reset.set_defaults(func=cmd_reset)

    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
