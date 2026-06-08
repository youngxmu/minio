from dataclasses import dataclass
from typing import Dict, Iterable, List

from .local_state import LocalStateStore
from .manifest import ManifestVideo
from .mc import McCommandBuilder


@dataclass(frozen=True)
class MigrationConfig:
    batch_id: str
    source_id: str
    source_alias: str
    target_id: str
    cold_bucket: str
    cold_prefix: str
    tier_name: str
    max_migratable_bytes: int = 0


@dataclass(frozen=True)
class MetadataRequest:
    operation: str
    endpoint: str
    payload: Dict


@dataclass(frozen=True)
class MigrationPlan:
    batch_id: str
    video: ManifestVideo
    lifecycle_prefix: str
    lifecycle_rule_command: List[str]
    metadata_requests: List[MetadataRequest]


class MigrationPlanner:
    def __init__(self, config: MigrationConfig, command_builder: McCommandBuilder = None):
        self.config = config
        self.command_builder = command_builder or McCommandBuilder()

    def plan_videoid_smoke(
        self,
        videos: Iterable[ManifestVideo],
        company_id: int,
        station_id: int,
        video_id: int,
    ) -> MigrationPlan:
        selected = [
            video
            for video in videos
            if video.source_id == self.config.source_id
            and video.company_id == company_id
            and video.station_id == station_id
            and video.video_id == video_id
        ]
        if not selected:
            raise ValueError("no manifest video matched source/company/station/video identity")
        if len(selected) > 1:
            raise ValueError("multiple manifest videos matched source/company/station/video identity")

        video = selected[0]
        lifecycle_prefix = derive_common_object_prefix([obj.key for obj in video.objects])
        lifecycle_rule_command = self.command_builder.add_lifecycle_rule(
            source_alias=self.config.source_alias,
            bucket=video.bucket,
            prefix=lifecycle_prefix,
            tier_name=self.config.tier_name,
        )
        metadata_requests = self._metadata_requests(video)
        return MigrationPlan(
            batch_id=self.config.batch_id,
            video=video,
            lifecycle_prefix=lifecycle_prefix,
            lifecycle_rule_command=lifecycle_rule_command,
            metadata_requests=metadata_requests,
        )

    def write_plan_to_local_state(self, store: LocalStateStore, plan: MigrationPlan) -> None:
        store.upsert_batch(
            batch_id=plan.batch_id,
            source_id=self.config.source_id,
            target_id=self.config.target_id,
            status="PLANNED",
            detail={"lifecyclePrefix": plan.lifecycle_prefix},
        )
        for obj in plan.video.objects:
            store.upsert_object(
                batch_id=plan.batch_id,
                source_id=plan.video.source_id,
                source_bucket=plan.video.bucket,
                source_key=obj.key,
                source_version_id="",
                company_id=plan.video.company_id,
                station_id=plan.video.station_id,
                video_id=plan.video.video_id,
                file_role=obj.role,
                status="PLANNED",
            )
        for request in plan.metadata_requests:
            store.enqueue_outbox(
                operation=request.operation,
                endpoint=request.endpoint,
                payload=request.payload,
                batch_id=plan.batch_id,
            )
        store.record_event(
            batch_id=plan.batch_id,
            event_type="plan-created",
            message="migration plan created",
            detail={"objectCount": len(plan.video.objects), "lifecyclePrefix": plan.lifecycle_prefix},
        )

    def _metadata_requests(self, video: ManifestVideo) -> List[MetadataRequest]:
        batch_payload = {
            "batchId": self.config.batch_id,
            "sourceId": self.config.source_id,
            "targetId": self.config.target_id,
            "sourceBucket": video.bucket,
            "coldBucket": self.config.cold_bucket,
            "coldPrefix": self.config.cold_prefix,
            "tierName": self.config.tier_name,
            "status": "PLANNED",
            "maxMigratableBytes": self.config.max_migratable_bytes,
            "plannedObjectCount": len(video.objects),
        }
        video_payload = {
            "sourceId": video.source_id,
            "companyId": video.company_id,
            "stationId": video.station_id,
            "videoId": video.video_id,
            "requiredObjectCount": len([obj for obj in video.objects if obj.required]),
            "migrationStatus": "PLANNED",
        }
        requests = [
            MetadataRequest("upsert-batch", "/api/v1/batches", batch_payload),
            MetadataRequest("upsert-batch-video", "/api/v1/batches/{}/videos".format(self.config.batch_id), video_payload),
        ]
        for obj in video.objects:
            requests.append(
                MetadataRequest(
                    "upsert-object",
                    "/api/v1/objects/upsert",
                    {
                        "sourceId": video.source_id,
                        "companyId": video.company_id,
                        "stationId": video.station_id,
                        "videoId": video.video_id,
                        "fileRole": obj.role,
                        "required": obj.required,
                        "sourceBucket": video.bucket,
                        "sourceKey": obj.key,
                        "objectStatus": "PLANNED",
                        "transitionBatchId": self.config.batch_id,
                    },
                )
            )
        return requests


def derive_common_object_prefix(keys: Iterable[str]) -> str:
    keys = list(keys)
    if not keys:
        raise ValueError("at least one object key is required")

    split_keys = [key.split("/")[:-1] for key in keys]
    common = []
    for parts in zip(*split_keys):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])

    if not common:
        raise ValueError("object keys do not share a safe directory prefix")
    return "/".join(common) + "/"
