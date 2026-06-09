import argparse
import json
import os

from .local_state import LocalStateStore
from .manifest import read_manifest
from .mc import McCommandBuilder
from .migrator import MigrationConfig, MigrationPlanner
from .outbox_sync import sync_outbox
from .small_file_smoke import SmallFileSmokeConfig, SmallFileSmokeRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cold-backup")
    subparsers = parser.add_subparsers(dest="command", required=True)

    small = subparsers.add_parser("small-file-smoke")
    small.add_argument("--plan-only", action="store_true", help="validate CLI shape without touching MinIO")
    small.add_argument("--state-db", default="cold-backup-small-file-smoke.sqlite3")
    small.add_argument("--batch-id")
    small.add_argument("--source-id")
    small.add_argument("--source-alias")
    small.add_argument("--source-endpoint")
    small.add_argument("--source-bucket")
    small.add_argument("--source-prefix")
    small.add_argument("--target-id")
    small.add_argument("--cold-alias")
    small.add_argument("--cold-endpoint")
    small.add_argument("--cold-bucket")
    small.add_argument("--cold-prefix")
    small.add_argument("--tier-name")
    small.add_argument("--cold-access-key")
    small.add_argument("--cold-secret-key")
    small.add_argument("--cold-access-key-env")
    small.add_argument("--cold-secret-key-env")
    small.add_argument("--work-dir", default="cold-backup-small-file-smoke-work")
    small.add_argument("--company-id", type=int, default=0)
    small.add_argument("--station-id", type=int, default=0)
    small.add_argument("--video-id", type=int, default=0)
    small.add_argument("--file-size-bytes", type=int, default=8 * 1024 * 1024)
    small.add_argument("--poll-interval-seconds", type=float, default=30)
    small.add_argument("--timeout-seconds", type=float, default=1800)
    small.add_argument("--mc-binary", default="mc")
    small.add_argument("--make-cold-public", action="store_true")

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
    sync.add_argument("--api-key")
    sync.add_argument("--api-key-env")
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


def run_sync_outbox(args, sync_func=sync_outbox) -> dict:
    api_key = _optional_arg_or_env(args, "api_key", "api_key_env")
    store = LocalStateStore(args.state_db)
    store.initialize()
    try:
        return sync_func(store, args.api_base_url, limit=args.limit, api_key=api_key)
    finally:
        store.close()


def run_small_file_smoke(args, runner_factory=SmallFileSmokeRunner) -> dict:
    _require_args(
        args,
        [
            "batch_id",
            "source_id",
            "source_alias",
            "source_endpoint",
            "source_bucket",
            "source_prefix",
            "target_id",
            "cold_alias",
            "cold_endpoint",
            "cold_bucket",
            "cold_prefix",
            "tier_name",
            "work_dir",
        ],
    )
    cold_access_key = _arg_or_env(args, "cold_access_key", "cold_access_key_env")
    cold_secret_key = _arg_or_env(args, "cold_secret_key", "cold_secret_key_env")
    store = LocalStateStore(args.state_db)
    store.initialize()
    try:
        runner = runner_factory(
            config=SmallFileSmokeConfig(
                batch_id=args.batch_id,
                source_id=args.source_id,
                source_alias=args.source_alias,
                source_endpoint=args.source_endpoint,
                source_bucket=args.source_bucket,
                source_prefix=args.source_prefix,
                target_id=args.target_id,
                cold_alias=args.cold_alias,
                cold_endpoint=args.cold_endpoint,
                cold_bucket=args.cold_bucket,
                cold_prefix=args.cold_prefix,
                tier_name=args.tier_name,
                cold_access_key=cold_access_key,
                cold_secret_key=cold_secret_key,
                work_dir=args.work_dir,
                company_id=args.company_id,
                station_id=args.station_id,
                video_id=args.video_id,
                file_size_bytes=args.file_size_bytes,
                poll_interval_seconds=args.poll_interval_seconds,
                timeout_seconds=args.timeout_seconds,
                make_cold_public=args.make_cold_public,
            ),
            state_store=store,
            command_builder=McCommandBuilder(args.mc_binary),
        )
        return runner.run()
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
        if args.plan_only:
            print(json.dumps({"status": "planned", "command": args.command}, sort_keys=True))
            return 0
        print(json.dumps(run_small_file_smoke(args), ensure_ascii=False, sort_keys=True))
        return 0
    if args.command == "sync-outbox":
        print(json.dumps(run_sync_outbox(args), sort_keys=True))
        return 0
    raise SystemExit(args.command + " command is parsed but not implemented yet")


def _require_args(args, names) -> None:
    missing = [name.replace("_", "-") for name in names if getattr(args, name, None) in (None, "")]
    if missing:
        raise SystemExit("missing required arguments for small-file-smoke: " + ", ".join("--" + name for name in missing))


def _arg_or_env(args, value_name: str, env_name: str) -> str:
    value = getattr(args, value_name, None)
    if value:
        return value
    env_var = getattr(args, env_name, None)
    if env_var:
        value = os.environ.get(env_var)
        if value:
            return value
        raise SystemExit("environment variable is empty for small-file-smoke: " + env_var)
    raise SystemExit(
        "missing required arguments for small-file-smoke: --{} or --{}-env".format(
            value_name.replace("_", "-"),
            value_name.replace("_", "-"),
        )
    )


def _optional_arg_or_env(args, value_name: str, env_name: str):
    value = getattr(args, value_name, None)
    if value:
        return value
    env_var = getattr(args, env_name, None)
    if not env_var:
        return None
    value = os.environ.get(env_var)
    if value:
        return value
    raise SystemExit("environment variable is empty: " + env_var)


if __name__ == "__main__":
    raise SystemExit(main())
