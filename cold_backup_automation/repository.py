import json
from typing import Any, Dict, Iterable, Optional

from .api_models import (
    BatchPayload,
    EventPayload,
    MappingPayload,
    ObjectPayload,
    SourcePayload,
    TargetPayload,
    VideoPayload,
    sha256_text,
)


class SucaiMetaRepository:
    def __init__(self, connection):
        self.connection = connection

    def upsert_source(self, payload: SourcePayload) -> Dict[str, Any]:
        columns = [
            "source_id",
            "source_name",
            "endpoint",
            "minio_version",
            "service_type",
            "status",
            "config_json",
        ]
        self._upsert("meta_source", columns, payload.to_record(), ["source_name", "endpoint", "minio_version", "service_type", "status", "config_json"])
        return {"sourceId": payload.source_id, "status": "upserted"}

    def upsert_target(self, payload: TargetPayload) -> Dict[str, Any]:
        columns = [
            "target_id",
            "target_name",
            "endpoint",
            "minio_version",
            "cold_bucket",
            "cold_prefix",
            "tier_name",
            "usable_free_bytes",
            "status",
            "config_json",
        ]
        self._upsert(
            "meta_target",
            columns,
            payload.to_record(),
            ["target_name", "endpoint", "minio_version", "cold_bucket", "cold_prefix", "tier_name", "usable_free_bytes", "status", "config_json"],
        )
        return {"targetId": payload.target_id, "status": "upserted"}

    def upsert_batch(self, payload: BatchPayload) -> Dict[str, Any]:
        columns = [
            "batch_id",
            "source_id",
            "target_id",
            "source_bucket",
            "cold_bucket",
            "cold_prefix",
            "tier_name",
            "status",
            "max_migratable_bytes",
            "planned_object_bytes",
            "planned_object_count",
            "manifest_uri",
        ]
        self._upsert(
            "meta_migration_batch",
            columns,
            payload.to_record(),
            ["source_id", "target_id", "source_bucket", "cold_bucket", "cold_prefix", "tier_name", "status", "max_migratable_bytes", "planned_object_bytes", "planned_object_count", "manifest_uri"],
        )
        return {"batchId": payload.batch_id, "status": "upserted"}

    def upsert_video(self, payload: VideoPayload) -> Dict[str, Any]:
        columns = [
            "source_id",
            "company_id",
            "station_id",
            "video_id",
            "user_id",
            "account_id",
            "video_status",
            "business_create_time",
            "business_update_time",
            "migration_status",
            "required_object_count",
        ]
        self._upsert(
            "meta_video",
            columns,
            payload.to_record(),
            ["user_id", "account_id", "video_status", "business_create_time", "business_update_time", "migration_status", "required_object_count"],
        )
        return {"sourceId": payload.source_id, "companyId": payload.company_id, "stationId": payload.station_id, "videoId": payload.video_id, "status": "upserted"}

    def attach_video_to_batch(self, batch_id: str, payload: VideoPayload) -> Dict[str, Any]:
        record = {
            "batch_id": batch_id,
            "source_id": payload.source_id,
            "company_id": payload.company_id,
            "station_id": payload.station_id,
            "video_id": payload.video_id,
            "status": payload.migration_status,
        }
        columns = ["batch_id", "source_id", "company_id", "station_id", "video_id", "status"]
        self._upsert("meta_batch_video", columns, record, ["status"])
        return {"batchId": batch_id, "sourceId": payload.source_id, "companyId": payload.company_id, "stationId": payload.station_id, "videoId": payload.video_id, "status": "attached"}

    def upsert_batch_video(self, batch_id: str, payload: VideoPayload) -> Dict[str, Any]:
        self.upsert_video(payload)
        return self.attach_video_to_batch(batch_id, payload)

    def upsert_object(self, payload: ObjectPayload) -> Dict[str, Any]:
        columns = [
            "source_id",
            "company_id",
            "station_id",
            "video_id",
            "file_role",
            "required_role",
            "source_bucket",
            "source_key",
            "source_key_sha256",
            "source_version_id",
            "source_etag",
            "size_bytes",
            "sha256",
            "content_type",
            "user_metadata_json",
            "last_modified",
            "object_status",
            "storage_class",
            "transition_batch_id",
            "transition_time",
        ]
        self._upsert(
            "meta_object",
            columns,
            payload.to_record(),
            ["required_role", "source_etag", "size_bytes", "sha256", "content_type", "user_metadata_json", "last_modified", "object_status", "storage_class", "transition_batch_id", "transition_time"],
        )
        return {"sourceId": payload.source_id, "companyId": payload.company_id, "stationId": payload.station_id, "videoId": payload.video_id, "fileRole": payload.file_role, "status": "upserted"}

    def upsert_mapping(self, payload: MappingPayload) -> Dict[str, Any]:
        columns = [
            "source_id",
            "company_id",
            "station_id",
            "video_id",
            "file_role",
            "meta_object_id",
            "source_bucket",
            "source_key",
            "source_key_sha256",
            "source_version_id",
            "source_size_bytes",
            "source_sha256",
            "target_id",
            "cold_bucket",
            "cold_prefix",
            "cold_object_key",
            "cold_object_key_sha256",
            "cold_size_bytes",
            "cold_sha256",
            "tier_name",
            "transition_batch_id",
            "match_status",
            "verify_status",
            "restore_status",
            "delete_status",
            "ambiguity_group_id",
            "transition_time",
            "mapped_at",
            "verified_at",
            "restored_at",
            "deleted_at",
        ]
        self._upsert(
            "meta_object_mapping",
            columns,
            payload.to_record(),
            ["meta_object_id", "source_size_bytes", "source_sha256", "target_id", "cold_bucket", "cold_prefix", "cold_object_key", "cold_object_key_sha256", "cold_size_bytes", "cold_sha256", "tier_name", "transition_batch_id", "match_status", "verify_status", "restore_status", "delete_status", "ambiguity_group_id", "transition_time", "mapped_at", "verified_at", "restored_at", "deleted_at"],
        )
        return {"sourceId": payload.source_id, "companyId": payload.company_id, "stationId": payload.station_id, "videoId": payload.video_id, "fileRole": payload.file_role, "status": "upserted"}

    def insert_event(self, payload: EventPayload) -> Dict[str, Any]:
        columns = [
            "batch_id",
            "source_id",
            "company_id",
            "station_id",
            "video_id",
            "object_id",
            "event_type",
            "event_level",
            "message",
            "detail_json",
        ]
        record = payload.to_record()
        self._execute(
            "INSERT INTO meta_event_log ({}) VALUES ({})".format(
                ", ".join(columns),
                ", ".join(["%s"] * len(columns)),
            ),
            self._params(record, columns),
            commit=True,
        )
        return {"eventType": payload.event_type, "status": "inserted"}

    def list_videos(self, company_id: int, station_id: int, video_id: int, source_id: Optional[str] = None):
        if source_id:
            sql = (
                "SELECT * FROM meta_video "
                "WHERE source_id=%s AND company_id=%s AND station_id=%s AND video_id=%s"
            )
            params = (source_id, company_id, station_id, video_id)
        else:
            sql = "SELECT * FROM meta_video WHERE company_id=%s AND station_id=%s AND video_id=%s"
            params = (company_id, station_id, video_id)
        return self._fetchall(sql, params)

    def lookup_mapping(self, source_id: str, bucket: str, key: str, version_id: str = ""):
        sql = (
            "SELECT * FROM meta_object_mapping "
            "WHERE source_id=%s AND source_bucket=%s AND source_key_sha256=%s AND source_version_id=%s"
        )
        return self._fetchone(sql, (source_id, bucket, sha256_text(key), version_id))

    def batch_summary(self, batch_id: str):
        sql = (
            "SELECT b.*, "
            "(SELECT COUNT(*) FROM meta_batch_video v WHERE v.batch_id=b.batch_id) AS video_count, "
            "(SELECT COUNT(*) FROM meta_object o WHERE o.transition_batch_id=b.batch_id) AS object_count, "
            "(SELECT COUNT(*) FROM meta_object_mapping m WHERE m.transition_batch_id=b.batch_id) AS mapping_count "
            "FROM meta_migration_batch b WHERE b.batch_id=%s"
        )
        return self._fetchone(sql, (batch_id,))

    def _upsert(self, table: str, columns: Iterable[str], record: Dict[str, Any], update_columns: Iterable[str]) -> None:
        columns = list(columns)
        update_columns = list(update_columns)
        sql = "INSERT INTO {} ({}) VALUES ({}) ON DUPLICATE KEY UPDATE {}".format(
            table,
            ", ".join(columns),
            ", ".join(["%s"] * len(columns)),
            ", ".join([column + "=VALUES(" + column + ")" for column in update_columns]),
        )
        self._execute(sql, self._params(record, columns), commit=True)

    def _execute(self, sql: str, params, commit: bool = False):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
        if commit:
            self.connection.commit()

    def _fetchone(self, sql: str, params):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def _fetchall(self, sql: str, params):
        with self.connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def _params(self, record: Dict[str, Any], columns: Iterable[str]):
        return tuple(self._json_value(record.get(column)) for column in columns)

    def _json_value(self, value):
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return value
