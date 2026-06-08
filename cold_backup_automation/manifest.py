import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from .api_models import sha256_text


KNOWN_FILE_ROLES = {
    "source_upload",
    "cover",
    "watermark_source",
    "transcoded_video",
    "playback_video",
}


class ManifestValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ManifestObject:
    role: str
    key: str
    required: bool
    source_key_sha256: str

    @classmethod
    def from_dict(cls, payload: Dict[str, Any], line_number: int, object_index: int) -> "ManifestObject":
        role = _required_str(payload, "role", line_number)
        if role not in KNOWN_FILE_ROLES:
            raise ManifestValidationError("line {} object {} unknown file role: {}".format(line_number, object_index, role))
        key = _required_str(payload, "key", line_number)
        required = payload.get("required", True)
        if not isinstance(required, bool):
            raise ManifestValidationError("line {} object {} required must be boolean".format(line_number, object_index))
        return cls(role=role, key=key, required=required, source_key_sha256=sha256_text(key))


@dataclass(frozen=True)
class ManifestVideo:
    source_id: str
    company_id: int
    station_id: int
    video_id: int
    bucket: str
    objects: List[ManifestObject]

    @property
    def identity(self) -> Tuple[str, int, int, int]:
        return (self.source_id, self.company_id, self.station_id, self.video_id)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any], line_number: int) -> "ManifestVideo":
        source_id = _required_str(payload, "sourceId", line_number)
        company_id = _required_int(payload, "companyId", line_number)
        station_id = _required_int(payload, "stationId", line_number)
        video_id = _required_int(payload, "videoId", line_number)
        bucket = _required_str(payload, "bucket", line_number)
        raw_objects = payload.get("objects")
        if not isinstance(raw_objects, list) or not raw_objects:
            raise ManifestValidationError("line {} objects must be a non-empty array".format(line_number))

        objects = []
        for index, item in enumerate(raw_objects):
            if not isinstance(item, dict):
                raise ManifestValidationError("line {} object {} must be an object".format(line_number, index))
            objects.append(ManifestObject.from_dict(item, line_number, index))

        return cls(
            source_id=source_id,
            company_id=company_id,
            station_id=station_id,
            video_id=video_id,
            bucket=bucket,
            objects=objects,
        )


def parse_manifest_lines(lines: Iterable[str]) -> List[ManifestVideo]:
    videos = []
    seen = set()
    for line_number, raw_line in enumerate(lines, 1):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ManifestValidationError("line {} invalid JSON: {}".format(line_number, exc.msg)) from exc
        if not isinstance(payload, dict):
            raise ManifestValidationError("line {} must contain one JSON object".format(line_number))

        video = ManifestVideo.from_dict(payload, line_number)
        if video.identity in seen:
            raise ManifestValidationError("line {} duplicate video identity: {}".format(line_number, video.identity))
        seen.add(video.identity)
        videos.append(video)
    return videos


def read_manifest(path: str) -> List[ManifestVideo]:
    with open(path, "r", encoding="utf-8") as manifest_file:
        return parse_manifest_lines(manifest_file)


def _required_str(payload: Dict[str, Any], field_name: str, line_number: int) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError("line {} missing required field: {}".format(line_number, field_name))
    return value


def _required_int(payload: Dict[str, Any], field_name: str, line_number: int) -> int:
    value = payload.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestValidationError("line {} missing required field: {}".format(line_number, field_name))
    return value
