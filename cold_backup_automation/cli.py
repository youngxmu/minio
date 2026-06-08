import argparse
import json

from .local_state import LocalStateStore
from .manifest import read_manifest
from .migrator import MigrationConfig, MigrationPlanner
from .outbox_sync import sync_outbox


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cold-backup")
    subparsers = parser.add_subparsers(dest="command", required=True)

    small = subparsers.add_parser("small-file-smoke")
    small.add_argument("--plan-only", action="store_true", help="validate CLI shape without touching MinIO")

    video = subparsers.add_parser("videoid-smoke")
    video.add_argument("--plan-only", action="store_true", help="create local state/outbox without executing mc commands")
    video.add_argument("--manifest", required=True)
    video.add_argument("--state-db", default="cold-backup-migrator.sqlite3")
    video.add_argument("--company-id", type=int, required=True)
    video.add_argument("--station-id", type=int, required=True)
    video.add_argument("--video-id", type=int, required=True)
    video.add_argument("--batch-id", required=True)
    video.add_argument("--source-id", required=True)
    video.add_argument("--source-alias", required=True)
    video.add_argument("--target-id", required=True)
    video.add_argument("--cold-bucket", required=True)
    video.add_argument("--cold-prefix", required=True)
    video.add_argument("--tier-name", required=True)
    video.add_argument("--max-migratable-bytes", type=int, default=0)

    sync = subparsers.add_parser("sync-outbox")
    sync.add_argument("--state-db", required=True)
    sync.add_argument("--api-base-url", required=True)
    sync.add_argument("--limit", type=int, default=100)

    summary = subparsers.add_parser("batch-summary")
    summary.add_argument("--batch-id", required=True)
    summary.add_argument("--api-base-url")
    summary.add_argument("--state-db")

    return parser


def run_videoid_smoke_plan(args) -> dict:
    videos = read_manifest(args.manifest)
    planner = MigrationPlanner(
        MigrationConfig(
            batch_id=args.batch_id,
            source_id=args.source_id,
            source_alias=args.source_alias,
            target_id=args.target_id,
            cold_bucket=args.cold_bucket,
            cold_prefix=args.cold_prefix,
            tier_name=args.tier_name,
            max_migratable_bytes=args.max_migratable_bytes,
        )
    )
    plan = planner.plan_videoid_smoke(
        videos,
        company_id=args.company_id,
        station_id=args.station_id,
        video_id=args.video_id,
    )
    store = LocalStateStore(args.state_db)
    store.initialize()
    try:
        planner.write_plan_to_local_state(store, plan)
    finally:
        store.close()

    return {
        "batchId": plan.batch_id,
        "sourceId": args.source_id,
        "companyId": args.company_id,
        "stationId": args.station_id,
        "videoId": args.video_id,
        "lifecyclePrefix": plan.lifecycle_prefix,
        "objectCount": len(plan.video.objects),
        "lifecycleRuleCommand": plan.lifecycle_rule_command,
    }


def run_sync_outbox(args) -> dict:
    store = LocalStateStore(args.state_db)
    store.initialize()
    try:
        return sync_outbox(store, args.api_base_url, limit=args.limit)
    finally:
        store.close()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "videoid-smoke":
        if not args.plan_only:
            raise SystemExit("videoid-smoke currently requires --plan-only until mc execution is implemented")
        print(json.dumps(run_videoid_smoke_plan(args), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "small-file-smoke":
        if not args.plan_only:
            raise SystemExit("small-file-smoke currently requires --plan-only until mc execution is implemented")
        print(json.dumps({"status": "planned", "command": args.command}, sort_keys=True))
        return 0
    if args.command == "sync-outbox":
        print(json.dumps(run_sync_outbox(args), sort_keys=True))
        return 0
    raise SystemExit(args.command + " command is parsed but not implemented yet")


if __name__ == "__main__":
    raise SystemExit(main())
