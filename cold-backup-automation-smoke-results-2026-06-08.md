# Cold Backup Automation Smoke Results - 2026-06-08

> Scope: A380 local metadata database and automation smoke.
> Host role: local test oldminio host.

## Result

The local automation stack passed the metadata smoke on A380.

Validated:

```text
sucai_meta schema applied on A380 MySQL
all meta_ tables created
dedicated metadata API database user created outside this repo
FastAPI dependency environment created
repository-level MySQL write/read smoke passed
FastAPI HTTP write/read smoke passed
videoid-smoke --plan-only wrote local SQLite state/outbox
sync-outbox posted local outbox requests to FastAPI
batch summary showed planned video/object rows
```

This smoke did not execute real MinIO lifecycle transition yet.

## A380 Environment Notes

Observed:

```text
Python: 3.14.4
MySQL client/server line: 8.4.9 Ubuntu package
MinIO processes: source MinIO processes were present
Root filesystem free space: about 217G available during smoke
```

`python3.14-venv` was missing and was installed through apt to keep API dependencies isolated in a venv.

Installed venv packages:

```text
fastapi 0.136.3
pymysql 2.2.8
uvicorn 0.49.0
```

## MySQL Schema Smoke

Applied:

```text
db/sucai_meta_schema.sql
```

Tables verified:

```text
meta_batch_video
meta_event_log
meta_migration_batch
meta_object
meta_object_mapping
meta_source
meta_sync_receipt
meta_target
meta_video
```

Operational note:

```text
plain sudo mysql failed because the root account path hit mysql_native_password plugin loading
sudo mysql --defaults-file=/etc/mysql/debian.cnf worked
```

The API DSN is stored only on A380 in a private env file under the test directory.

## Repository MySQL Smoke

Inserted and queried:

```text
source: a380-smoke-oldminio1
target: a380-smoke-newminio1
batch: a380-api-smoke-20260608100307
video identity: source_id=a380-smoke-oldminio1, company_id=100, station_id=200, video_id=14708948
mapping lookup: true
summary counts: video=1, object=1, mapping=1
```

## FastAPI HTTP Smoke

Temporary API:

```text
host: 127.0.0.1
port: 18080
```

Validated:

```text
GET /healthz
POST /api/v1/sources
POST /api/v1/targets
POST /api/v1/batches
GET /api/v1/batches/{batchId}/summary
```

HTTP batch:

```text
a380-http-smoke-20260608180347
```

Summary returned the inserted batch row from `sucai_meta.meta_migration_batch`.

## Plan/Outbox Smoke

Manifest:

```json
{"sourceId":"a380-plan-oldminio1","companyId":100,"stationId":200,"videoId":14708948,"bucket":"sucaiwang","objects":[{"role":"cover","key":"sucaiwang/100/200/plan-cover.jpg"},{"role":"playback_video","key":"sucaiwang/100/200/plan-video.mp4"}]}
```

Command shape:

```text
python -m cold_backup_automation.cli videoid-smoke --plan-only ...
python -m cold_backup_automation.cli sync-outbox ...
```

Generated lifecycle rule command:

```text
mc ilm rule add old1/sucaiwang --prefix sucaiwang/100/200/ --transition-days 0 --transition-tier COLD_A380_PLAN_SMOKE
```

Sync result:

```text
sent=4
failed=0
```

Final batch summary:

```text
batch_id=a380-plan-smoke-20260608
video_count=1
object_count=2
mapping_count=0
status=PLANNED
```

## Remaining Work

Next smoke should execute real MinIO operations:

```text
create small source objects
verify or add cold tier
add narrow lifecycle rule
wait for transition
match cold payload by size and SHA256
sync mapping rows
delete through source and verify cold cleanup
remove batch lifecycle rule
```

Keep production rollout blocked until the real MinIO lifecycle smoke passes through the automation path.
