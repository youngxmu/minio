# Video Location Index Design

> Date: 2026-06-03
> Scope: dual-MinIO hot/cold test and later Java production change reference.

## 1. Purpose

The dual-MinIO design needs one resolver before every output read:

```text
videoId -> current object location
```

The push task must not hard-code a bucket or host. It should resolve the output location by `videoId`, prefer SSD when a hot copy exists, and fall back to HDD after the hot copy is evicted.

For the benchmark, this resolver is a local SQLite file. For production, the same model should become a Java-side table or persistent service.

## 2. Test Index

Default test DB path:

```text
/root/dual-minio-io-test/video-location-index.sqlite3
```

When push simulation runs from A380 or A770, place a copy of the DB on that client:

```text
/home/user/dual-minio-io-test/video-location-index.sqlite3
```

This is acceptable for controlled benchmark runs because test object keys are deterministic. Production must use one authoritative shared store instead of copied SQLite files.

## 3. State Model

The test DB tracks:

| Field group | Meaning |
| --- | --- |
| `video_id` | Business video id used by Java and push tasks. |
| `active_tier` | Current preferred serving tier: `ssd` or `hdd`. |
| hot location | SSD endpoint, bucket, object key, and whether the hot copy exists. |
| cold location | HDD endpoint, bucket, object key, and whether the archive copy exists. |
| status | Current lifecycle status such as `hot_ready`, `archived`, or `hot_evicted`. |
| push counters | Push read count and last push timestamp for test verification. |

Resolution rule:

```text
prefer=ssd:
  if hot_present: return SSD location
  else if cold_present: return HDD location

prefer=active:
  use active_tier first, then fall back to any existing copy

prefer=hdd:
  if cold_present: return HDD location
  else if hot_present: return SSD location
```

## 4. Lifecycle

### Transcode Complete

After A770 writes output to hot SSD MinIO:

```bash
python3 scripts/video_location_index.py \
  --db video-location-index.sqlite3 \
  set-hot \
  --video-id calib-000001 \
  --endpoint-name hot-ssd \
  --endpoint http://172.16.100.217:19400 \
  --bucket dual-output-hot \
  --key calib-dual-out-000001.bin \
  --size-bytes 536870912
```

Expected state:

```text
hot_present=1
active_tier=ssd
```

### Push Task

Push resolves by `videoId` and reads from the preferred location:

```bash
python3 scripts/dual_minio_s3bench.py push \
  --index-db video-location-index.sqlite3 \
  --video-id calib-000001 \
  --prefer ssd \
  --record-push
```

Expected behavior:

```text
If SSD copy exists: GET from hot SSD MinIO.
If SSD copy was evicted and HDD copy exists: GET from cold HDD MinIO.
```

### Archive Complete

After the archive worker copies SSD output to HDD:

```bash
python3 scripts/video_location_index.py \
  --db video-location-index.sqlite3 \
  set-cold \
  --video-id calib-000001 \
  --endpoint-name cold-hdd \
  --endpoint http://172.16.100.217:19300 \
  --bucket dual-output-archive \
  --key calib-dual-archive-000001.bin
```

Expected state:

```text
hot_present=1
cold_present=1
active_tier=ssd
```

Archive completion must not switch reads to HDD while the SSD hot copy is still valid.

### Hot Eviction

When the hot tier needs space and the HDD archive is confirmed:

```bash
python3 scripts/video_location_index.py \
  --db video-location-index.sqlite3 \
  evict-hot \
  --video-id calib-000001
```

Expected state:

```text
hot_present=0
cold_present=1
active_tier=hdd
```

## 5. Bulk Registration for Benchmarks

For deterministic generated objects:

```bash
python3 scripts/video_location_index.py \
  --db video-location-index.sqlite3 \
  register-range \
  --tier ssd \
  --video-prefix calib-dual-video- \
  --object-prefix calib-dual-out- \
  --count 160 \
  --endpoint-name hot-ssd \
  --endpoint http://172.16.100.217:19400 \
  --bucket dual-output-hot \
  --size-bytes 536870912
```

For baseline HDD-only output:

```bash
python3 scripts/video_location_index.py \
  --db video-location-index.sqlite3 \
  register-range \
  --tier hdd \
  --video-prefix calib-hdd-video- \
  --object-prefix calib-hdd-out- \
  --count 160 \
  --endpoint-name hdd-only \
  --endpoint http://172.16.100.217:19200 \
  --bucket hdd-only-output \
  --size-bytes 536870912 \
  --make-active
```

## 6. Production Java Change Target

The production Java project should introduce an authoritative object-location model with these minimum fields:

| Field | Purpose |
| --- | --- |
| `video_id` | Primary lookup key for read/download/push. |
| `active_tier` | Preferred serving tier: `ssd` or `hdd`. |
| `hot_bucket`, `hot_key`, `hot_endpoint` | SSD hot location. |
| `hot_present` | Whether SSD object is currently valid. |
| `cold_bucket`, `cold_key`, `cold_endpoint` | HDD archive location. |
| `cold_present` | Whether HDD object is currently valid. |
| `updated_at`, `archived_at` | Lifecycle timestamps. |

Required Java behavior:

```text
1. Upload path records raw object location.
2. Transcode completion records hot output location and sets active_tier=ssd.
3. Push and download paths resolve by videoId before reading.
4. Resolver prefers SSD and falls back to HDD only when SSD is unavailable.
5. Archive worker writes cold location without changing active_tier while hot exists.
6. Hot cleanup only evicts SSD after cold_present is true.
7. All state changes must be idempotent.
```

The object URL shape should remain stable for callers. The resolver changes host/bucket selection internally.

## 7. Cleanup

For full benchmark reset on 4070S:

```bash
sudo bash scripts/reset_dual_minio_test.sh --yes --remove-results
```

Use `--remove-loopback` only when the 200G SSD loopback image should be deleted too.
