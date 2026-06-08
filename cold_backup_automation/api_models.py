import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional, Tuple


class PayloadValidationError(ValueError):
    pass


_MISSING = object()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _get(payload: Dict[str, Any], camel_name: str, snake_name: Optional[str] = None, default: Any = _MISSING) -> Any:
    if camel_name in payload:
        return payload[camel_name]
    if snake_name and snake_name in payload:
        return payload[snake_name]
    if default is not _MISSING:
        return default
    raise PayloadValidationError("missing required field: " + camel_name)


def _required_str(payload: Dict[str, Any], camel_name: str, snake_name: Optional[str] = None) -> str:
    value = _get(payload, camel_name, snake_name)
    if not isinstance(value, str) or not value.strip():
        raise PayloadValidationError("field must be a non-empty string: " + camel_name)
    return value


def _optional_str(
    payload: Dict[str, Any],
    camel_name: str,
    snake_name: Optional[str] = None,
    default: Optional[str] = None,
) -> Optional[str]:
    value = _get(payload, camel_name, snake_name, default)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PayloadValidationError("field must be a string: " + camel_name)
    return value


def _required_int(payload: Dict[str, Any], camel_name: str, snake_name: Optional[str] = None) -> int:
    value = _get(payload, camel_name, snake_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PayloadValidationError("field must be an integer: " + camel_name)
    return value


def _optional_int(
    payload: Dict[str, Any],
    camel_name: str,
    snake_name: Optional[str] = None,
    default: Optional[int] = None,
) -> Optional[int]:
    value = _get(payload, camel_name, snake_name, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PayloadValidationError("field must be an integer: " + camel_name)
    return value


def _optional_bool(payload: Dict[str, Any], camel_name: str, snake_name: Optional[str] = None, default: bool = True) -> bool:
    value = _get(payload, camel_name, snake_name, default)
    if not isinstance(value, bool):
        raise PayloadValidationError("field must be a boolean: " + camel_name)
    return value


def _optional_json(payload: Dict[str, Any], camel_name: str, snake_name: Optional[str] = None) -> Any:
    return _get(payload, camel_name, snake_name, None)


def _record(instance: Any) -> Dict[str, Any]:
    return asdict(instance)


@dataclass(frozen=True)
class SourcePayload:
    source_id: str
    source_name: str
    endpoint: str
    minio_version: str
    service_type: str
    status: str = "ACTIVE"
    config_json: Any = None

    @classmethod
    def from_api(cls, payload: Dict[str, Any]) -> "SourcePayload":
        return cls(
            source_id=_required_str(payload, "sourceId", "source_id"),
            source_name=_required_str(payload, "sourceName", "source_name"),
            endpoint=_required_str(payload, "endpoint"),
            minio_version=_required_str(payload, "minioVersion", "minio_version"),
            service_type=_required_str(payload, "serviceType", "service_type"),
            status=_optional_str(payload, "status", default="ACTIVE") or "ACTIVE",
            config_json=_optional_json(payload, "config", "config_json"),
        )

    def to_record(self) -> Dict[str, Any]:
        return _record(self)


@dataclass(frozen=True)
class TargetPayload:
    target_id: str
    target_name: str
    endpoint: str
    minio_version: str
    cold_bucket: str
    cold_prefix: str
    tier_name: str
    usable_free_bytes: int
    status: str = "ACTIVE"
    config_json: Any = None

    @classmethod
    def from_api(cls, payload: Dict[str, Any]) -> "TargetPayload":
        return cls(
            target_id=_required_str(payload, "targetId", "target_id"),
            target_name=_required_str(payload, "targetName", "target_name"),
            endpoint=_required_str(payload, "endpoint"),
            minio_version=_required_str(payload, "minioVersion", "minio_version"),
            cold_bucket=_required_str(payload, "coldBucket", "cold_bucket"),
            cold_prefix=_required_str(payload, "coldPrefix", "cold_prefix"),
            tier_name=_required_str(payload, "tierName", "tier_name"),
            usable_free_bytes=_required_int(payload, "usableFreeBytes", "usable_free_bytes"),
            status=_optional_str(payload, "status", default="ACTIVE") or "ACTIVE",
            config_json=_optional_json(payload, "config", "config_json"),
        )

    def to_record(self) -> Dict[str, Any]:
        return _record(self)


@dataclass(frozen=True)
class BatchPayload:
    batch_id: str
    source_id: str
    target_id: str
    source_bucket: str
    cold_bucket: str
    cold_prefix: str
    tier_name: str
    status: str = "CREATED"
    max_migratable_bytes: Optional[int] = None
    planned_object_bytes: int = 0
    planned_object_count: int = 0
    manifest_uri: Optional[str] = None

    @classmethod
    def from_api(cls, payload: Dict[str, Any]) -> "BatchPayload":
        return cls(
            batch_id=_required_str(payload, "batchId", "batch_id"),
            source_id=_required_str(payload, "sourceId", "source_id"),
            target_id=_required_str(payload, "targetId", "target_id"),
            source_bucket=_required_str(payload, "sourceBucket", "source_bucket"),
            cold_bucket=_required_str(payload, "coldBucket", "cold_bucket"),
            cold_prefix=_required_str(payload, "coldPrefix", "cold_prefix"),
            tier_name=_required_str(payload, "tierName", "tier_name"),
            status=_optional_str(payload, "status", default="CREATED") or "CREATED",
            max_migratable_bytes=_optional_int(payload, "maxMigratableBytes", "max_migratable_bytes"),
            planned_object_bytes=_optional_int(payload, "plannedObjectBytes", "planned_object_bytes", 0) or 0,
            planned_object_count=_optional_int(payload, "plannedObjectCount", "planned_object_count", 0) or 0,
            manifest_uri=_optional_str(payload, "manifestUri", "manifest_uri"),
        )

    def to_record(self) -> Dict[str, Any]:
        return _record(self)


@dataclass(frozen=True)
class VideoPayload:
    source_id: str
    company_id: int
    station_id: int
    video_id: int
    user_id: Optional[int] = None
    account_id: Optional[int] = None
    video_status: Optional[str] = None
    business_create_time: Optional[str] = None
    business_update_time: Optional[str] = None
    migration_status: str = "PENDING"
    required_object_count: int = 0

    @property
    def identity(self) -> Tuple[str, int, int, int]:
        return (self.source_id, self.company_id, self.station_id, self.video_id)

    @classmethod
    def from_api(cls, payload: Dict[str, Any]) -> "VideoPayload":
        return cls(
            source_id=_required_str(payload, "sourceId", "source_id"),
            company_id=_required_int(payload, "companyId", "company_id"),
            station_id=_required_int(payload, "stationId", "station_id"),
            video_id=_required_int(payload, "videoId", "video_id"),
            user_id=_optional_int(payload, "userId", "user_id"),
            account_id=_optional_int(payload, "accountId", "account_id"),
            video_status=_optional_str(payload, "videoStatus", "video_status"),
            business_create_time=_optional_str(payload, "businessCreateTime", "business_create_time"),
            business_update_time=_optional_str(payload, "businessUpdateTime", "business_update_time"),
            migration_status=_optional_str(payload, "migrationStatus", "migration_status", "PENDING") or "PENDING",
            required_object_count=_optional_int(payload, "requiredObjectCount", "required_object_count", 0) or 0,
        )

    def to_record(self) -> Dict[str, Any]:
        return _record(self)


@dataclass(frozen=True)
class ObjectPayload:
    source_id: str
    company_id: int
    station_id: int
    video_id: int
    file_role: str
    required_role: bool
    source_bucket: str
    source_key: str
    source_key_sha256: str
    source_version_id: str = ""
    source_etag: Optional[str] = None
    size_bytes: int = 0
    sha256: Optional[str] = None
    content_type: Optional[str] = None
    user_metadata_json: Any = None
    last_modified: Optional[str] = None
    object_status: str = "PENDING"
    storage_class: Optional[str] = None
    transition_batch_id: Optional[str] = None
    transition_time: Optional[str] = None

    @property
    def identity(self) -> Tuple[str, int, int, int, str]:
        return (self.source_id, self.company_id, self.station_id, self.video_id, self.file_role)

    @classmethod
    def from_api(cls, payload: Dict[str, Any]) -> "ObjectPayload":
        source_key = _required_str(payload, "sourceKey", "source_key")
        return cls(
            source_id=_required_str(payload, "sourceId", "source_id"),
            company_id=_required_int(payload, "companyId", "company_id"),
            station_id=_required_int(payload, "stationId", "station_id"),
            video_id=_required_int(payload, "videoId", "video_id"),
            file_role=_required_str(payload, "fileRole", "file_role"),
            required_role=_optional_bool(payload, "required", "required_role", True),
            source_bucket=_required_str(payload, "sourceBucket", "source_bucket"),
            source_key=source_key,
            source_key_sha256=sha256_text(source_key),
            source_version_id=_optional_str(payload, "sourceVersionId", "source_version_id", "") or "",
            source_etag=_optional_str(payload, "sourceEtag", "source_etag"),
            size_bytes=_optional_int(payload, "sizeBytes", "size_bytes", 0) or 0,
            sha256=_optional_str(payload, "sha256"),
            content_type=_optional_str(payload, "contentType", "content_type"),
            user_metadata_json=_optional_json(payload, "userMetadata", "user_metadata_json"),
            last_modified=_optional_str(payload, "lastModified", "last_modified"),
            object_status=_optional_str(payload, "objectStatus", "object_status", "PENDING") or "PENDING",
            storage_class=_optional_str(payload, "storageClass", "storage_class"),
            transition_batch_id=_optional_str(payload, "transitionBatchId", "transition_batch_id"),
            transition_time=_optional_str(payload, "transitionTime", "transition_time"),
        )

    def to_record(self) -> Dict[str, Any]:
        return _record(self)


@dataclass(frozen=True)
class MappingPayload:
    source_id: str
    company_id: int
    station_id: int
    video_id: int
    file_role: str
    source_bucket: str
    source_key: str
    source_key_sha256: str
    source_sha256: str
    target_id: str
    cold_bucket: str
    cold_prefix: str
    cold_object_key: str
    cold_object_key_sha256: str
    cold_sha256: str
    tier_name: str
    transition_batch_id: str
    source_version_id: str = ""
    source_size_bytes: int = 0
    cold_size_bytes: int = 0
    match_status: str = "PENDING"
    verify_status: str = "PENDING"
    restore_status: str = "NOT_RESTORED"
    delete_status: str = "NOT_DELETED"
    ambiguity_group_id: Optional[str] = None
    transition_time: Optional[str] = None
    mapped_at: Optional[str] = None
    verified_at: Optional[str] = None
    restored_at: Optional[str] = None
    deleted_at: Optional[str] = None
    meta_object_id: Optional[int] = None

    @classmethod
    def from_api(cls, payload: Dict[str, Any]) -> "MappingPayload":
        source_key = _required_str(payload, "sourceKey", "source_key")
        cold_object_key = _required_str(payload, "coldObjectKey", "cold_object_key")
        return cls(
            source_id=_required_str(payload, "sourceId", "source_id"),
            company_id=_required_int(payload, "companyId", "company_id"),
            station_id=_required_int(payload, "stationId", "station_id"),
            video_id=_required_int(payload, "videoId", "video_id"),
            file_role=_required_str(payload, "fileRole", "file_role"),
            source_bucket=_required_str(payload, "sourceBucket", "source_bucket"),
            source_key=source_key,
            source_key_sha256=sha256_text(source_key),
            source_sha256=_required_str(payload, "sourceSha256", "source_sha256"),
            target_id=_required_str(payload, "targetId", "target_id"),
            cold_bucket=_required_str(payload, "coldBucket", "cold_bucket"),
            cold_prefix=_required_str(payload, "coldPrefix", "cold_prefix"),
            cold_object_key=cold_object_key,
            cold_object_key_sha256=sha256_text(cold_object_key),
            cold_sha256=_required_str(payload, "coldSha256", "cold_sha256"),
            tier_name=_required_str(payload, "tierName", "tier_name"),
            transition_batch_id=_required_str(payload, "transitionBatchId", "transition_batch_id"),
            source_version_id=_optional_str(payload, "sourceVersionId", "source_version_id", "") or "",
            source_size_bytes=_optional_int(payload, "sourceSizeBytes", "source_size_bytes", 0) or 0,
            cold_size_bytes=_optional_int(payload, "coldSizeBytes", "cold_size_bytes", 0) or 0,
            match_status=_optional_str(payload, "matchStatus", "match_status", "PENDING") or "PENDING",
            verify_status=_optional_str(payload, "verifyStatus", "verify_status", "PENDING") or "PENDING",
            restore_status=_optional_str(payload, "restoreStatus", "restore_status", "NOT_RESTORED") or "NOT_RESTORED",
            delete_status=_optional_str(payload, "deleteStatus", "delete_status", "NOT_DELETED") or "NOT_DELETED",
            ambiguity_group_id=_optional_str(payload, "ambiguityGroupId", "ambiguity_group_id"),
            transition_time=_optional_str(payload, "transitionTime", "transition_time"),
            mapped_at=_optional_str(payload, "mappedAt", "mapped_at"),
            verified_at=_optional_str(payload, "verifiedAt", "verified_at"),
            restored_at=_optional_str(payload, "restoredAt", "restored_at"),
            deleted_at=_optional_str(payload, "deletedAt", "deleted_at"),
            meta_object_id=_optional_int(payload, "metaObjectId", "meta_object_id"),
        )

    def to_record(self) -> Dict[str, Any]:
        return _record(self)


@dataclass(frozen=True)
class EventPayload:
    event_type: str
    message: str
    batch_id: Optional[str] = None
    source_id: Optional[str] = None
    company_id: Optional[int] = None
    station_id: Optional[int] = None
    video_id: Optional[int] = None
    object_id: Optional[int] = None
    event_level: str = "INFO"
    detail_json: Any = None

    @classmethod
    def from_api(cls, payload: Dict[str, Any]) -> "EventPayload":
        return cls(
            event_type=_required_str(payload, "eventType", "event_type"),
            message=_required_str(payload, "message"),
            batch_id=_optional_str(payload, "batchId", "batch_id"),
            source_id=_optional_str(payload, "sourceId", "source_id"),
            company_id=_optional_int(payload, "companyId", "company_id"),
            station_id=_optional_int(payload, "stationId", "station_id"),
            video_id=_optional_int(payload, "videoId", "video_id"),
            object_id=_optional_int(payload, "objectId", "object_id"),
            event_level=_optional_str(payload, "eventLevel", "event_level", "INFO") or "INFO",
            detail_json=_optional_json(payload, "detail", "detail_json"),
        )

    def to_record(self) -> Dict[str, Any]:
        return _record(self)
