import hashlib
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional


def sha256_json(payload: Dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class LocalStateStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection = None

    @property
    def connection(self):
        if self._connection is None:
            parent = os.path.dirname(self.db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            self._connection = sqlite3.connect(self.db_path)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def initialize(self) -> None:
        conn = self.connection
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS local_batch_state (
              batch_id TEXT NOT NULL PRIMARY KEY,
              source_id TEXT NULL,
              target_id TEXT NULL,
              status TEXT NOT NULL,
              manifest_uri TEXT NULL,
              detail_json TEXT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS local_object_state (
              id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
              batch_id TEXT NOT NULL,
              source_id TEXT NOT NULL,
              source_bucket TEXT NOT NULL,
              source_key TEXT NOT NULL,
              source_key_sha256 TEXT NOT NULL,
              source_version_id TEXT NOT NULL DEFAULT '',
              company_id INTEGER NOT NULL,
              station_id INTEGER NOT NULL,
              video_id INTEGER NOT NULL,
              file_role TEXT NOT NULL,
              status TEXT NOT NULL,
              size_bytes INTEGER NOT NULL DEFAULT 0,
              detail_json TEXT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              UNIQUE (batch_id, source_id, source_bucket, source_key_sha256, source_version_id)
            );

            CREATE TABLE IF NOT EXISTS local_sync_outbox (
              id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
              operation TEXT NOT NULL,
              endpoint TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              request_hash TEXT NOT NULL,
              batch_id TEXT NULL,
              status TEXT NOT NULL DEFAULT 'PENDING',
              attempt_count INTEGER NOT NULL DEFAULT 0,
              last_error TEXT NULL,
              response_status TEXT NULL,
              response_json TEXT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              sent_at TEXT NULL,
              UNIQUE (operation, endpoint, request_hash)
            );

            CREATE TABLE IF NOT EXISTS local_event_log (
              id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
              batch_id TEXT NULL,
              event_type TEXT NOT NULL,
              event_level TEXT NOT NULL DEFAULT 'INFO',
              message TEXT NOT NULL,
              detail_json TEXT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.commit()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def upsert_batch(
        self,
        batch_id: str,
        source_id: Optional[str],
        target_id: Optional[str],
        status: str,
        manifest_uri: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO local_batch_state
              (batch_id, source_id, target_id, status, manifest_uri, detail_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(batch_id) DO UPDATE SET
              source_id=excluded.source_id,
              target_id=excluded.target_id,
              status=excluded.status,
              manifest_uri=excluded.manifest_uri,
              detail_json=excluded.detail_json,
              updated_at=CURRENT_TIMESTAMP
            """,
            (batch_id, source_id, target_id, status, manifest_uri, _json_dumps(detail)),
        )
        self.connection.commit()

    def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            "SELECT * FROM local_batch_state WHERE batch_id=?",
            (batch_id,),
        ).fetchone()
        return _row_to_dict(row)

    def upsert_object(
        self,
        batch_id: str,
        source_id: str,
        source_bucket: str,
        source_key: str,
        source_version_id: str,
        company_id: int,
        station_id: int,
        video_id: int,
        file_role: str,
        status: str,
        size_bytes: int = 0,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        source_key_sha256 = sha256_text(source_key)
        self.connection.execute(
            """
            INSERT INTO local_object_state
              (batch_id, source_id, source_bucket, source_key, source_key_sha256,
               source_version_id, company_id, station_id, video_id, file_role,
               status, size_bytes, detail_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(batch_id, source_id, source_bucket, source_key_sha256, source_version_id)
            DO UPDATE SET
              source_key=excluded.source_key,
              company_id=excluded.company_id,
              station_id=excluded.station_id,
              video_id=excluded.video_id,
              file_role=excluded.file_role,
              status=excluded.status,
              size_bytes=excluded.size_bytes,
              detail_json=excluded.detail_json,
              updated_at=CURRENT_TIMESTAMP
            """,
            (
                batch_id,
                source_id,
                source_bucket,
                source_key,
                source_key_sha256,
                source_version_id or "",
                company_id,
                station_id,
                video_id,
                file_role,
                status,
                size_bytes,
                _json_dumps(detail),
            ),
        )
        self.connection.commit()

    def get_object(
        self,
        batch_id: str,
        source_id: str,
        source_bucket: str,
        source_key: str,
        source_version_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            """
            SELECT * FROM local_object_state
            WHERE batch_id=? AND source_id=? AND source_bucket=?
              AND source_key_sha256=? AND source_version_id=?
            """,
            (batch_id, source_id, source_bucket, sha256_text(source_key), source_version_id or ""),
        ).fetchone()
        return _row_to_dict(row)

    def enqueue_outbox(
        self,
        operation: str,
        endpoint: str,
        payload: Dict[str, Any],
        batch_id: Optional[str] = None,
    ) -> int:
        payload_json = _json_dumps(payload)
        request_hash = sha256_json(payload)
        self.connection.execute(
            """
            INSERT OR IGNORE INTO local_sync_outbox
              (operation, endpoint, payload_json, request_hash, batch_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (operation, endpoint, payload_json, request_hash, batch_id),
        )
        row = self.connection.execute(
            """
            SELECT id FROM local_sync_outbox
            WHERE operation=? AND endpoint=? AND request_hash=?
            """,
            (operation, endpoint, request_hash),
        ).fetchone()
        self.connection.commit()
        return int(row["id"])

    def next_outbox(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT * FROM local_sync_outbox
            WHERE status IN ('PENDING', 'FAILED')
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def mark_outbox_sent(self, item_id: int, response_status: str, response_json: Optional[Dict[str, Any]] = None) -> None:
        self.connection.execute(
            """
            UPDATE local_sync_outbox
            SET status='SENT',
                response_status=?,
                response_json=?,
                updated_at=CURRENT_TIMESTAMP,
                sent_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (response_status, _json_dumps(response_json), item_id),
        )
        self.connection.commit()

    def mark_outbox_failed(self, item_id: int, error_message: str) -> None:
        self.connection.execute(
            """
            UPDATE local_sync_outbox
            SET status='FAILED',
                attempt_count=attempt_count + 1,
                last_error=?,
                updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (error_message, item_id),
        )
        self.connection.commit()

    def record_event(
        self,
        batch_id: Optional[str],
        event_type: str,
        message: str,
        event_level: str = "INFO",
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO local_event_log
              (batch_id, event_type, event_level, message, detail_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (batch_id, event_type, event_level, message, _json_dumps(detail)),
        )
        self.connection.commit()

    def list_events(self, batch_id: str) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM local_event_log WHERE batch_id=? ORDER BY id ASC",
            (batch_id,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]


def _json_dumps(value: Optional[Dict[str, Any]]) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row_to_dict(row) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    data = dict(row)
    for key in list(data.keys()):
        if key.endswith("_json") and data[key] is not None:
            data[key] = json.loads(data[key])
    return data
