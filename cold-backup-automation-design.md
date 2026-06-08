# Cold Backup Automation Design

> Date: 2026-06-08
> Scope: local-test design for the cold-backup migration automation system.

## 1. Updated Decision

The local test environment will use A380 as the first integrated test host:

```text
A380 oldminio host
  old MinIO source
  MySQL database: sucai_meta
  cold-backup-meta-api
  cold-backup-migrator

newminio
  cold MinIO target
```

The metadata database name is:

```text
sucai_meta
```

Table naming rule:

```text
all cold-backup metadata tables use the meta_ prefix
```

The business identity for any video-level record is:

```text
company_id + station_id + video_id
```

Do not treat `video_id` alone as unique. Different companies and stations can reuse the same `video_id`.

## 2. Core Architecture

```text
manifest source
  -> cold-backup-migrator on oldminio
  -> local SQLite state and outbox
  -> cold-backup-meta-api
  -> MySQL sucai_meta
  -> restore/query/export workflows
```

The local SQLite file remains useful, but only as a worker-local reliability layer:

```text
resume after process restart
store API outbox when the metadata API is temporarily unavailable
record local evidence for the current batch
avoid high-frequency synchronous writes to MySQL for every polling tick
```

The authoritative test metadata store is MySQL `sucai_meta`.

The production business database is not changed in this design.

## 3. Component Responsibilities

### cold-backup-meta-api

Responsibilities:

```text
create and update migration batches
register migration sources and cold targets
upsert video identities by company_id + station_id + video_id
upsert object rows for each video file role
upsert source-to-cold mapping rows
record transition, verify, restore, and delete statuses
serve lookup APIs for recovery and audit
```

It writes only to `sucai_meta`.

### cold-backup-migrator

Runs on oldminio.

Responsibilities:

```text
read JSONL manifest or call a candidate video API
validate each video object group
operate mc / MinIO lifecycle transition
poll source objects until storage class changes
discover cold internal keys
match by size and SHA256
write local SQLite state
sync batch updates to cold-backup-meta-api
perform small-file smoke, videoId smoke, delete smoke, and restore drill
```

### local SQLite

Recommended file:

```text
/data/migration-state/cold-backup-migrator.sqlite3
```

If A380 system disk has limited space, do not place the SQLite state under the root filesystem.

The SQLite file is not the final recovery index. It is a local work ledger and outbox.

## 4. Input Design

First implementation should support JSONL manifest input.

Each line represents one business video:

```json
{
  "companyId": 100192,
  "stationId": 1079,
  "videoId": 14708948,
  "sourceId": "oldminio1",
  "bucket": "sucaiwang",
  "objects": [
    {"role": "source_upload", "key": "sucaiwang/100192/15624/example.MOV", "required": true},
    {"role": "cover", "key": "sucaiwang/100192/15624/example.jpg", "required": true},
    {"role": "watermark_source", "key": "sucaiwang/100192/15624/example_mark919.MOV", "required": true},
    {"role": "transcoded_video", "key": "sucaiwang/100192/15624/example_h265.MOV", "required": true},
    {"role": "playback_video", "key": "sucaiwang/100192/15624/example.mp4", "required": true}
  ]
}
```

Later implementation can add a candidate API:

```text
GET /candidate-videos?beforeTime=&limit=&sourceId=
```

The migrator should still persist the returned candidates as a batch manifest before running MinIO operations.

## 5. MySQL Schema Principles

Schema file:

```text
db/sucai_meta_schema.sql
```

Rules:

```text
database name: sucai_meta
all table names start with meta_
company_id, station_id, video_id are NOT NULL on video/object/mapping tables
video identity unique key includes source_id, company_id, station_id, video_id
object identity unique key includes source_id, company_id, station_id, video_id, file_role, source bucket/key hash, and version id
long object keys are stored as TEXT plus SHA256 columns for stable indexes
```

The source object key is not indexed directly as full `TEXT`. Use:

```text
source_key TEXT
source_key_sha256 CHAR(64)
```

The cold object key uses the same pattern:

```text
cold_object_key TEXT
cold_object_key_sha256 CHAR(64)
```

## 6. API Shape

API accepts camelCase payloads and stores snake_case database columns.

Core endpoints:

```text
POST /api/v1/sources
POST /api/v1/targets
POST /api/v1/batches
POST /api/v1/batches/{batchId}/videos
POST /api/v1/objects/upsert
POST /api/v1/mappings/upsert
POST /api/v1/events
GET  /api/v1/videos/{companyId}/{stationId}/{videoId}
GET  /api/v1/mappings/lookup?sourceId=&bucket=&key=
GET  /api/v1/batches/{batchId}/summary
```

The first API implementation can be Python FastAPI for the local test.

Runtime configuration:

```text
SUCAI_META_DSN=mysql://<user>:<password>@127.0.0.1:3306/sucai_meta?charset=utf8mb4
```

Store the real DSN outside this repo.

## 7. Status Model

Batch status:

```text
CREATED
MANIFEST_READY
RUNNING
PAUSED
COMPLETED
FAILED
STOPPED
```

Video status:

```text
PENDING
COMPLETE
PARTIAL
ACTIVE
UNKNOWN_LAYOUT
TRANSITIONING
TRANSITIONED
MAPPED
RESTORE_VERIFIED
FAILED
```

Object status:

```text
PENDING
SOURCE_VERIFIED
ALREADY_TIERED
TRANSITIONING
TRANSITIONED
MAPPED
VERIFY_FAILED
DELETE_REQUESTED
DELETED
FAILED
```

Mapping status:

```text
PENDING
EXACT
DUPLICATE_PAYLOAD
AMBIGUOUS
MISSING
FAILED
```

## 8. Capacity And Window Controls

Required newminio config:

```text
endpoint
access key and secret key
cold bucket
cold prefix
tier name
MinIO version
usable_free_bytes or a supported capacity probe
```

Default migration cap:

```text
max_migratable_bytes = usable_free_bytes * 0.5
```

If `usable_free_bytes` cannot be calculated safely from newminio, the config must provide it explicitly.

Time window behavior:

```text
start new lifecycle rules only inside the allowed window
do not create broad rules near the end of a window
finish or safely stop the current small batch when the window closes
```

## 9. First Execution Scope

Build the local test in this order:

1. Create `sucai_meta` DDL with `meta_` tables and identity keys.
2. Add a small Python config/capacity helper with tests.
3. Build FastAPI metadata service against A380 MySQL.
4. Build local SQLite outbox.
5. Build JSONL manifest parser.
6. Build small-file smoke command.
7. Build single-videoId migration command.
8. Build mapping lookup and restore export.

Do not implement broad production scheduling until the local A380 test passes.
