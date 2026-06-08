import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional

from .local_state import LocalStateStore
from .mc import McCommandBuilder


@dataclass(frozen=True)
class SmallFileSmokeConfig:
    batch_id: str
    source_id: str
    source_alias: str
    source_endpoint: str
    source_bucket: str
    source_prefix: str
    target_id: str
    cold_alias: str
    cold_endpoint: str
    cold_bucket: str
    cold_prefix: str
    tier_name: str
    cold_access_key: str
    cold_secret_key: str
    work_dir: str
    company_id: int = 0
    station_id: int = 0
    video_id: int = 0
    file_size_bytes: int = 8 * 1024 * 1024
    poll_interval_seconds: float = 30
    timeout_seconds: float = 1800
    make_cold_public: bool = False


@dataclass(frozen=True)
class _SmokeObject:
    file_role: str
    source_key: str
    local_path: str
    sha256: str
    size_bytes: int
    cold_object_key: str = ""
    cold_sha256: str = ""


class ShellMcRunner:
    def run(self, command: List[str], input_bytes: bytes = None):
        import subprocess

        try:
            result = subprocess.run(command, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError as exc:
            stderr = _redact_text(_to_text(exc.stderr), command).strip()
            raise RuntimeError(
                "mc command failed exit={} command={} stderr={}".format(
                    exc.returncode,
                    " ".join(_redact_command(command)),
                    stderr,
                )
            ) from None
        try:
            return result.stdout.decode("utf-8")
        except UnicodeDecodeError:
            return result.stdout


class SmallFileSmokeRunner:
    def __init__(
        self,
        config: SmallFileSmokeConfig,
        mc_runner=None,
        http_code: Callable[[str], str] = None,
        state_store: Optional[LocalStateStore] = None,
        command_builder: McCommandBuilder = None,
    ):
        self.config = config
        self.mc_runner = mc_runner or ShellMcRunner()
        self.http_code = http_code or _default_http_code
        self.state_store = state_store
        self.command_builder = command_builder or McCommandBuilder()

    def run(self) -> Dict[str, str]:
        verify_object, delete_object = self._prepare_objects()
        objects = [verify_object, delete_object]

        self._initialize_local_state(objects)
        self._run(self.command_builder.make_bucket(self.config.cold_alias, self.config.cold_bucket))
        if self.config.make_cold_public:
            self._run(self.command_builder.anonymous_download(self.config.cold_alias, self.config.cold_bucket))

        for obj in objects:
            self._run(self.command_builder.cp(obj.local_path, self.config.source_alias, self.config.source_bucket, obj.source_key))

        lifecycle_prefix = _join_prefix(self.config.source_prefix)
        self._run(
            self.command_builder.add_minio_tier(
                source_alias=self.config.source_alias,
                tier_name=self.config.tier_name,
                endpoint=self.config.cold_endpoint,
                access_key=self.config.cold_access_key,
                secret_key=self.config.cold_secret_key,
                bucket=self.config.cold_bucket,
                prefix=_join_prefix(self.config.cold_prefix),
            )
        )
        self._run(
            self.command_builder.add_lifecycle_rule(
                source_alias=self.config.source_alias,
                bucket=self.config.source_bucket,
                prefix=lifecycle_prefix,
                tier_name=self.config.tier_name,
            )
        )

        for obj in objects:
            self._wait_for_transition(obj.source_key)

        cold_objects = self._match_cold_objects(objects)
        rule_ids = self._find_matching_lifecycle_rule_ids(lifecycle_prefix)
        for rule_id in rule_ids:
            self._run(self.command_builder.remove_lifecycle_rule(self.config.source_alias, self.config.source_bucket, rule_id))

        self._record_mappings(cold_objects)

        delete_cold = cold_objects["small_file_delete"]
        self._run(self.command_builder.rm(self.config.source_alias, self.config.source_bucket, delete_object.source_key))
        delete_source_code = self._wait_for_http_code(self._source_url(delete_object.source_key), "404")
        delete_cold_code = self._wait_for_http_code(self._cold_url(delete_cold.cold_object_key), "404")

        verify_cold = cold_objects["small_file_verify"]
        return {
            "batchId": self.config.batch_id,
            "transition": "OK",
            "verifySourceUrl": self._source_url(verify_object.source_key),
            "verifyColdUrl": self._cold_url(verify_cold.cold_object_key),
            "deleteSourceUrl": self._source_url(delete_object.source_key),
            "deleteColdUrl": self._cold_url(delete_cold.cold_object_key),
            "deleteSourceFinalCode": str(delete_source_code),
            "deleteColdFinalCode": str(delete_cold_code),
            "mappingCount": str(len(cold_objects)),
        }

    def _prepare_objects(self) -> List[_SmokeObject]:
        files_dir = os.path.join(self.config.work_dir, "files")
        os.makedirs(files_dir, exist_ok=True)
        return [
            self._write_object("small_file_verify", "verify.bin", files_dir),
            self._write_object("small_file_delete", "delete.bin", files_dir),
        ]

    def _write_object(self, file_role: str, filename: str, files_dir: str) -> _SmokeObject:
        local_path = os.path.join(files_dir, filename)
        with open(local_path, "wb") as f:
            f.write(os.urandom(self.config.file_size_bytes))
        return _SmokeObject(
            file_role=file_role,
            source_key=_join_key(self.config.source_prefix, filename),
            local_path=local_path,
            sha256=_sha256_file(local_path),
            size_bytes=os.path.getsize(local_path),
        )

    def _initialize_local_state(self, objects: Iterable[_SmokeObject]) -> None:
        if self.state_store is None:
            return
        self.state_store.upsert_batch(
            batch_id=self.config.batch_id,
            source_id=self.config.source_id,
            target_id=self.config.target_id,
            status="SMALL_FILE_SMOKE_RUNNING",
            detail={"sourcePrefix": self.config.source_prefix, "coldPrefix": self.config.cold_prefix},
        )
        for obj in objects:
            self.state_store.upsert_object(
                batch_id=self.config.batch_id,
                source_id=self.config.source_id,
                source_bucket=self.config.source_bucket,
                source_key=obj.source_key,
                source_version_id="",
                company_id=self.config.company_id,
                station_id=self.config.station_id,
                video_id=self.config.video_id,
                file_role=obj.file_role,
                status="SMALL_FILE_SMOKE_UPLOADED",
                size_bytes=obj.size_bytes,
                detail={"sha256": obj.sha256},
            )
        self.state_store.record_event(
            batch_id=self.config.batch_id,
            event_type="small-file-smoke-started",
            message="small file smoke started",
        )

    def _wait_for_transition(self, source_key: str) -> None:
        deadline = time.monotonic() + self.config.timeout_seconds
        while True:
            raw = self._run(self.command_builder.stat_json(self.config.source_alias, self.config.source_bucket, source_key))
            if _extract_storage_class(raw) == self.config.tier_name:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("object did not transition to tier: " + source_key)
            time.sleep(self.config.poll_interval_seconds)

    def _match_cold_objects(self, objects: List[_SmokeObject]) -> Dict[str, _SmokeObject]:
        cold_prefix = _join_prefix(self.config.cold_prefix)
        listed = self._run(self.command_builder.list_recursive_json(self.config.cold_alias, self.config.cold_bucket, cold_prefix))
        candidates = _parse_mc_json_lines(listed)
        matches: Dict[str, _SmokeObject] = {}
        for candidate in candidates:
            if candidate.get("type") != "file":
                continue
            key = _cold_key_from_listing(cold_prefix, candidate.get("key", ""))
            raw = self._run(self.command_builder.cat(self.config.cold_alias, self.config.cold_bucket, key))
            digest = _sha256_bytes(raw)
            for obj in objects:
                if obj.file_role not in matches and obj.sha256 == digest:
                    matches[obj.file_role] = _SmokeObject(
                        file_role=obj.file_role,
                        source_key=obj.source_key,
                        local_path=obj.local_path,
                        sha256=obj.sha256,
                        size_bytes=obj.size_bytes,
                        cold_object_key=key,
                        cold_sha256=digest,
                    )
                    break
        missing = [obj.file_role for obj in objects if obj.file_role not in matches]
        if missing:
            raise ValueError("cold object sha256 match not found for roles: " + ",".join(missing))
        return matches

    def _find_matching_lifecycle_rule_ids(self, lifecycle_prefix: str) -> List[str]:
        raw = self._run(self.command_builder.export_lifecycle_rules(self.config.source_alias, self.config.source_bucket))
        return _extract_rule_ids(raw, lifecycle_prefix, self.config.tier_name)

    def _record_mappings(self, cold_objects: Dict[str, _SmokeObject]) -> None:
        if self.state_store is None:
            return
        for obj in cold_objects.values():
            self.state_store.enqueue_outbox(
                operation="upsert-mapping",
                endpoint="/api/v1/mappings/upsert",
                payload={
                    "sourceId": self.config.source_id,
                    "companyId": self.config.company_id,
                    "stationId": self.config.station_id,
                    "videoId": self.config.video_id,
                    "fileRole": obj.file_role,
                    "sourceBucket": self.config.source_bucket,
                    "sourceKey": obj.source_key,
                    "sourceSha256": obj.sha256,
                    "targetId": self.config.target_id,
                    "coldBucket": self.config.cold_bucket,
                    "coldPrefix": _join_prefix(self.config.cold_prefix),
                    "coldObjectKey": obj.cold_object_key,
                    "coldSha256": obj.cold_sha256,
                    "tierName": self.config.tier_name,
                    "transitionBatchId": self.config.batch_id,
                    "sourceSizeBytes": obj.size_bytes,
                    "coldSizeBytes": obj.size_bytes,
                    "matchStatus": "EXACT",
                    "verifyStatus": "VERIFIED",
                },
                batch_id=self.config.batch_id,
            )
        self.state_store.record_event(
            batch_id=self.config.batch_id,
            event_type="small-file-smoke-mapped",
            message="small file cold mappings recorded",
            detail={"mappingCount": len(cold_objects)},
        )

    def _wait_for_http_code(self, url: str, expected_code: str) -> str:
        deadline = time.monotonic() + self.config.timeout_seconds
        while True:
            code = str(self.http_code(url))
            if code == expected_code:
                return code
            if time.monotonic() >= deadline:
                return code
            time.sleep(self.config.poll_interval_seconds)

    def _source_url(self, key: str) -> str:
        return _url(self.config.source_endpoint, self.config.source_bucket, key)

    def _cold_url(self, key: str) -> str:
        return _url(self.config.cold_endpoint, self.config.cold_bucket, key)

    def _run(self, command: List[str]):
        return self.mc_runner.run(command)


def _default_http_code(url: str) -> str:
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, method="GET", headers={"Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return str(response.status)
    except urllib.error.HTTPError as exc:
        return str(exc.code)


def _join_key(prefix: str, filename: str) -> str:
    return prefix.strip("/") + "/" + filename


def _join_prefix(prefix: str) -> str:
    return prefix.strip("/") + "/"


def _url(endpoint: str, bucket: str, key: str) -> str:
    return endpoint.rstrip("/") + "/" + bucket.strip("/") + "/" + key.lstrip("/")


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _extract_storage_class(raw) -> str:
    data = json.loads(_to_text(raw) or "{}")
    for key in ("storageClass", "StorageClass"):
        value = data.get(key)
        if value:
            return value
    metadata = data.get("metadata") or data.get("Metadata") or {}
    for key in ("X-Amz-Storage-Class", "x-amz-storage-class", "storage-class"):
        value = metadata.get(key)
        if value:
            return value
    return "STANDARD"


def _parse_mc_json_lines(raw) -> List[Dict]:
    text = _to_text(raw)
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _cold_key_from_listing(cold_prefix: str, listed_key: str) -> str:
    listed_key = listed_key.lstrip("/")
    if listed_key.startswith(cold_prefix):
        return listed_key
    return cold_prefix + listed_key


def _extract_rule_ids(raw, lifecycle_prefix: str, tier_name: str) -> List[str]:
    text = _to_text(raw)
    if not text.strip():
        return []
    rules = _parse_lifecycle_rules(text)
    rule_ids = []
    for rule in rules:
        prefix = _rule_prefix(rule)
        storage_class = _rule_storage_class(rule)
        if prefix == lifecycle_prefix and storage_class == tier_name:
            rule_id = rule.get("ID") or rule.get("id")
            if rule_id:
                rule_ids.append(rule_id)
    return rule_ids


def _parse_lifecycle_rules(text: str) -> List[Dict]:
    if text.lstrip().startswith("{"):
        data = json.loads(text)
        return data.get("Rules") or data.get("rules") or []

    import xml.etree.ElementTree as ET

    root = ET.fromstring(text)
    rules = []
    for rule in [elem for elem in root.iter() if _local_name(elem.tag) == "Rule"]:
        rules.append(
            {
                "ID": _child_text(rule, ["ID"]),
                "Filter": {"Prefix": _child_text(rule, ["Filter", "Prefix"])},
                "Transition": {"StorageClass": _child_text(rule, ["Transition", "StorageClass"])},
            }
        )
    return rules


def _child_text(element, path: List[str]) -> str:
    current = element
    for name in path:
        current = next((child for child in list(current) if _local_name(child.tag) == name), None)
        if current is None:
            return ""
    return current.text or ""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _rule_prefix(rule: Dict) -> str:
    if rule.get("Prefix"):
        return rule["Prefix"]
    rule_filter = rule.get("Filter") or rule.get("filter") or {}
    return rule_filter.get("Prefix") or rule_filter.get("prefix") or ""


def _rule_storage_class(rule: Dict) -> str:
    transition = rule.get("Transition") or rule.get("transition") or {}
    return transition.get("StorageClass") or transition.get("storageClass") or ""


def _to_text(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


def _redact_command(command: List[str]) -> List[str]:
    redacted = []
    mask_next = False
    for part in command:
        if mask_next:
            redacted.append("<redacted>")
            mask_next = False
            continue
        redacted.append(part)
        if part in ("--access-key", "--secret-key"):
            mask_next = True
    return redacted


def _redact_text(text: str, command: List[str]) -> str:
    redacted = text
    for index, part in enumerate(command[:-1]):
        if part in ("--access-key", "--secret-key"):
            redacted = redacted.replace(command[index + 1], "<redacted>")
    return redacted
