# Cold Backup Automation Small-File Results - 2026-06-08

> Scope: automated small-file lifecycle smoke from A380 old MinIO to 4070S cold MinIO.
> Runner: `python -m cold_backup_automation.cli small-file-smoke`.
> Batch: `automation-smoke-20260608-182702`.

## Result

The automated small-file smoke passed end to end.

Validated:

```text
created two 1 MiB source objects on A380 old MinIO
created/used the 4070S cold bucket
added a MinIO remote tier and a narrow lifecycle rule
waited until both source objects reported the cold storage class
matched the two cold internal objects by SHA256
removed the smoke lifecycle rule
deleted one transitioned object through the A380 source bucket/key
verified both source and cold internal URLs for the deleted object returned 404
kept one transitioned object readable through both source and cold URLs
recorded two local SQLite mapping outbox rows
synced both mapping rows to the A380 `sucai_meta` metadata API
```

## Test Objects

Batch identity:

```text
batch_id: automation-smoke-20260608-182702
source_id: oldminio1
source_alias: hot_minio
source_bucket: sucaiwang
source_prefix: sucaiwang/codex-automation-smoke/20260608/automation-smoke-20260608-182702
target_id: newminio1
cold_alias: cold_minio
cold_bucket: tier-a380-automation-smoke-20260608
cold_prefix: a380-9000/sucaiwang/automation-smoke-20260608/automation-smoke-20260608-182702/
tier_name: COLD_SMOKE_182702
object_size_each: 1048576 bytes
```

Retained verification object:

```text
source URL:
http://172.16.100.132:9000/sucaiwang/sucaiwang/codex-automation-smoke/20260608/automation-smoke-20260608-182702/verify.bin

cold URL:
http://172.16.100.217:9000/tier-a380-automation-smoke-20260608/a380-9000/sucaiwang/automation-smoke-20260608/automation-smoke-20260608-182702/709faf2a18b99804/22/92/229235bf-7643-4d4a-b721-0f25ef88f857
```

Deleted verification object:

```text
source URL:
http://172.16.100.132:9000/sucaiwang/sucaiwang/codex-automation-smoke/20260608/automation-smoke-20260608-182702/delete.bin

cold URL:
http://172.16.100.217:9000/tier-a380-automation-smoke-20260608/a380-9000/sucaiwang/automation-smoke-20260608/automation-smoke-20260608-182702/709faf2a18b99804/71/ba/71bab335-2d7f-479f-870c-18d4943c10c1
```

## Independent Verification

HTTP range-read results:

```text
VERIFY_SOURCE=206
VERIFY_COLD=206
DELETE_SOURCE=404
DELETE_COLD=404
```

Source object storage class:

```text
VERIFY_STORAGE_CLASS=COLD_SMOKE_182702
VERIFY_SIZE=1048576
```

Runner result JSON:

```json
{
  "batchId": "automation-smoke-20260608-182702",
  "deleteColdFinalCode": "404",
  "deleteSourceFinalCode": "404",
  "mappingCount": "2",
  "transition": "OK"
}
```

SQLite state:

```text
OBJECT_COUNT=2
OUTBOX_MAPPING_COUNT=2
```

After `sync-outbox` to the temporary A380 metadata API:

```text
sent=2
failed=0
local outbox statuses: SENT, SENT
```

Metadata lookup for `verify.bin` returned:

```text
source_id=oldminio1
file_role=small_file_verify
source_size_bytes=1048576
cold_size_bytes=1048576
match_status=EXACT
verify_status=VERIFIED
source_sha256 == cold_sha256
```

## Tooling Notes

A380 `/usr/local/bin/mc` segfaulted during this run. The smoke used a user-local MinIO client instead:

```text
mc RELEASE.2023-12-23T08-47-21Z
path: /home/user/cold-backup-automation/bin/mc-2023-12-23
wrapper: /home/user/cold-backup-automation/bin/mc-smoke
config dir: /home/user/cold-backup-automation/mc
```

The CLI supports `--cold-access-key-env` and `--cold-secret-key-env` so cold-tier credentials do not need to be passed as command-line arguments.

The temporary metadata API was started on `127.0.0.1:18082`, used for `sync-outbox`, and then stopped.

## Remaining Gap

This small-file runner syncs verified mapping rows. It does not create a full business batch/video/object summary because the smoke objects are synthetic and use `company_id=0`, `station_id=0`, `video_id=0`.

For production `videoId` migration, the execution order must be:

```text
1. generate or fetch videoId manifest
2. sync source/target/batch/video/object metadata
3. execute lifecycle transition
4. match cold objects
5. sync mapping rows
6. run restore or lookup drill
```

