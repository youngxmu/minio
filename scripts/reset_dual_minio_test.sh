#!/usr/bin/env bash
set -euo pipefail

DATA_ROOT="/data/data2/dual-minio-io-test"
HOT_ROOT="/mnt/minio-hot-ssd-test/minio-hot"
RESULTS_ROOT="/root/dual-minio-io-test/results"
INDEX_DB="/root/dual-minio-io-test/video-location-index.sqlite3"
HOT_MOUNT="/mnt/minio-hot-ssd-test"
LOOPBACK_IMAGE="/opt/dual-minio-io-test/hot-ssd-200g.img"
REMOVE_RESULTS=0
REMOVE_LOOPBACK=0
KEEP_CONTAINERS=0
YES=0

CONTAINERS=(
  minio_hdd_only_bench
  minio_cold_hdd_bench
  minio_hot_ssd_bench
)

usage() {
  cat <<'EOF'
Usage:
  reset_dual_minio_test.sh [options]

Default mode is dry-run. Pass --yes to actually delete data.

Options:
  --yes                 Execute cleanup. Required for deletion.
  --keep-containers     Do not stop/remove isolated benchmark MinIO containers.
  --remove-results      Delete benchmark result logs under /root/dual-minio-io-test/results.
  --remove-loopback     Unmount /mnt/minio-hot-ssd-test and delete the 200G loopback image.
  --data-root PATH      HDD test root. Default: /data/data2/dual-minio-io-test.
  --hot-root PATH       Hot MinIO data root. Default: /mnt/minio-hot-ssd-test/minio-hot.
  --index-db PATH       SQLite index DB path. Default: /root/dual-minio-io-test/video-location-index.sqlite3.
  --help                Show this help.

This script is intended to run on 4070S only. It never touches production MinIO
ports or existing SeaweedFS data paths.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --yes)
      YES=1
      ;;
    --keep-containers)
      KEEP_CONTAINERS=1
      ;;
    --remove-results)
      REMOVE_RESULTS=1
      ;;
    --remove-loopback)
      REMOVE_LOOPBACK=1
      ;;
    --data-root)
      DATA_ROOT="$2"
      shift
      ;;
    --hot-root)
      HOT_ROOT="$2"
      shift
      ;;
    --index-db)
      INDEX_DB="$2"
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

require_safe_path() {
  local value="$1"
  local label="$2"
  case "$value" in
    /data/data2/dual-minio-io-test|/data/data2/dual-minio-io-test/*)
      return 0
      ;;
    /mnt/minio-hot-ssd-test/minio-hot|/mnt/minio-hot-ssd-test/minio-hot/*)
      return 0
      ;;
    /root/dual-minio-io-test|/root/dual-minio-io-test/*)
      return 0
      ;;
    /opt/dual-minio-io-test|/opt/dual-minio-io-test/*)
      return 0
      ;;
    *)
      echo "refusing unsafe $label path: $value" >&2
      exit 3
      ;;
  esac
}

run_cmd() {
  echo "+ $*"
  if [ "$YES" -eq 1 ]; then
    "$@"
  fi
}

require_safe_path "$DATA_ROOT" "DATA_ROOT"
require_safe_path "$HOT_ROOT" "HOT_ROOT"
require_safe_path "$RESULTS_ROOT" "RESULTS_ROOT"
require_safe_path "$INDEX_DB" "INDEX_DB"
require_safe_path "$LOOPBACK_IMAGE" "LOOPBACK_IMAGE"

if [ "$YES" -ne 1 ]; then
  echo "DRY RUN: pass --yes to execute cleanup."
fi

if [ "$KEEP_CONTAINERS" -ne 1 ]; then
  for container in "${CONTAINERS[@]}"; do
    run_cmd docker rm -f "$container"
  done
fi

run_cmd rm -rf "${DATA_ROOT:?}/hdd-only" "${DATA_ROOT:?}/cold-hdd"
run_cmd mkdir -p "${DATA_ROOT:?}/hdd-only" "${DATA_ROOT:?}/cold-hdd"

run_cmd rm -rf "${HOT_ROOT:?}"
run_cmd mkdir -p "${HOT_ROOT:?}"

run_cmd rm -f "$INDEX_DB" "$INDEX_DB-shm" "$INDEX_DB-wal"

if [ "$REMOVE_RESULTS" -eq 1 ]; then
  run_cmd rm -rf "$RESULTS_ROOT"
  run_cmd mkdir -p "$RESULTS_ROOT"
fi

if [ "$REMOVE_LOOPBACK" -eq 1 ]; then
  if [ "$KEEP_CONTAINERS" -eq 1 ]; then
    echo "--remove-loopback cannot be used with --keep-containers" >&2
    exit 4
  fi
  if mountpoint -q "$HOT_MOUNT"; then
    run_cmd umount "$HOT_MOUNT"
  fi
  run_cmd rm -f "$LOOPBACK_IMAGE"
fi

echo "cleanup command finished"
