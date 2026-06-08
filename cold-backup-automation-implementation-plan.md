# Cold Backup Automation Implementation Plan

> Date: 2026-06-08
> Scope: implementation plan for the local A380 test automation system.

## Goal

Build an executable cold-backup migration automation system that can run on oldminio, operate MinIO lifecycle transition, and record authoritative migration metadata into MySQL database `sucai_meta`.

## Naming Constraints

```text
database: sucai_meta
tables: meta_ prefix
business video identity: source_id + company_id + station_id + video_id
video_id alone is never unique
```

## Phase 1 - Schema And Core Helpers

Status:

```text
completed locally
```

Files:

```text
db/sucai_meta_schema.sql
cold_backup_automation/config.py
tests/test_cold_backup_automation.py
```

Acceptance:

```text
schema creates database sucai_meta
all tables use meta_ prefix
video unique key includes source_id, company_id, station_id, video_id
object and mapping unique keys include company_id, station_id, video_id
default max migration size is 50% of usable newminio capacity
```

Verification:

```bash
python3 -m unittest tests/test_cold_backup_automation.py
python3 -m unittest discover -s tests
```

## Phase 2 - Metadata API

Status:

```text
implemented locally; FastAPI/MySQL integration smoke pending
```

Files to create:

```text
cold_backup_automation/api.py
cold_backup_automation/db.py
cold_backup_automation/repository.py
cold_backup_automation/api_models.py
requirements-cold-backup.txt
tests/test_cold_backup_api_models.py
tests/test_cold_backup_db.py
tests/test_cold_backup_repository.py
```

Recommended local stack:

```text
FastAPI
Uvicorn
PyMySQL or mysqlclient
Pydantic
```

Required endpoints:

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

API model rule:

```text
external JSON uses companyId, stationId, videoId
database columns use company_id, station_id, video_id
```

Acceptance:

```text
API can create source, target, batch, video, object, and mapping records
upsert APIs are idempotent by client_request_id or natural unique keys
duplicate video_id across company/station is accepted
duplicate source_id + company_id + station_id + video_id is rejected or updated idempotently
```

Local verification:

```bash
python3 -m unittest tests/test_cold_backup_api_models.py tests/test_cold_backup_db.py tests/test_cold_backup_repository.py
```

Runtime setup on oldminio:

```bash
python3 -m pip install -r requirements-cold-backup.txt
export SUCAI_META_DSN='mysql://<user>:<password>@127.0.0.1:3306/sucai_meta?charset=utf8mb4'
python3 -m uvicorn cold_backup_automation.api:app --host 0.0.0.0 --port 18080
```

Keep the real DSN outside this repo.

## Phase 3 - Local SQLite State And Outbox

Status:

```text
implemented locally
```

Files to create:

```text
cold_backup_automation/local_state.py
tests/test_cold_backup_local_state.py
```

SQLite purpose:

```text
local resumable state
API sync outbox
batch evidence index
no final recovery authority
```

Minimum local tables:

```text
local_batch_state
local_object_state
local_sync_outbox
local_event_log
```

Acceptance:

```text
migrator can enqueue API operations while API is unavailable
outbox retry is idempotent
local state survives process restart
```

Local verification:

```bash
python3 -m unittest tests/test_cold_backup_local_state.py
```

## Phase 4 - Manifest Parser

Status:

```text
implemented locally
```

Files to create:

```text
cold_backup_automation/manifest.py
tests/test_cold_backup_manifest.py
```

Input:

```text
JSONL, one video per line
companyId, stationId, videoId required
sourceId required
bucket required
objects array required
```

Acceptance:

```text
manifest rejects missing companyId/stationId/videoId
manifest allows same videoId under different companyId/stationId
manifest requires known file roles for first version
manifest computes source_key_sha256 for every object
```

Local verification:

```bash
python3 -m unittest tests/test_cold_backup_manifest.py
```

## Phase 5 - MinIO Migration Orchestrator

Status:

```text
planning and local outbox implemented; real mc execution pending A380 smoke
```

Files to create:

```text
cold_backup_automation/migrator.py
cold_backup_automation/mc.py
tests/test_cold_backup_migrator_planning.py
cold_backup_automation/cli.py
cold_backup_automation/outbox_sync.py
tests/test_cold_backup_cli.py
tests/test_cold_backup_outbox_sync.py
```

Responsibilities:

```text
validate mc connectivity
configure or verify cold tier
create narrow lifecycle rule
poll source storage class
snapshot cold prefix before and after
match cold objects by size and SHA256
remove batch lifecycle rules
call metadata API through outbox
```

First commands:

```text
small-file-smoke
videoid-smoke --manifest manifest.jsonl --video-id ID --company-id ID --station-id ID
sync-outbox
batch-summary
```

Acceptance:

```text
small-file smoke can transition verify.bin and delete.bin
delete smoke confirms source delete removes cold internal object
single videoId smoke migrates all required objects
mapping rows are synced to sucai_meta through API
```

Implemented local subset:

```text
mc command builder for tier/rule/stat/list/cat commands
videoId manifest selection by source_id + company_id + station_id + video_id
narrow lifecycle prefix planning
batch/video/object API requests written to local SQLite outbox
videoid-smoke --plan-only CLI
sync-outbox CLI posts local outbox requests to metadata API
```

Local verification:

```bash
python3 -m unittest tests/test_cold_backup_migrator_planning.py tests/test_cold_backup_cli.py tests/test_cold_backup_outbox_sync.py
```

## Phase 6 - A380 Integration Test

Prerequisites:

```text
A380 MySQL reachable locally on A380
database user created outside this repo
sucai_meta schema applied
metadata API started on A380
migrator config stored outside this repo
old MinIO and new MinIO versions aligned
```

Execution order:

1. Apply `db/sucai_meta_schema.sql` to A380 MySQL.
2. Start API service with `SUCAI_META_DSN` or equivalent private config.
3. Run API health check.
4. Run small-file smoke.
5. Verify rows in `sucai_meta.meta_migration_batch`.
6. Verify rows in `sucai_meta.meta_object_mapping`.
7. Run one videoId smoke.
8. Run mapping lookup and restore export.

Do not move to a production-like batch until this passes.

## Phase 7 - Production Hardening

Required before online deployment:

```text
authentication for metadata API
rate limit and migration window enforcement
structured logs
metrics
backup plan for sucai_meta
restore drill command
delete/versioning smoke for production bucket settings
systemd service files
operator runbook
```

## Current Next Step

Run a FastAPI/MySQL smoke on A380, then wire real `mc` execution and outbox sync for a small-file smoke.
