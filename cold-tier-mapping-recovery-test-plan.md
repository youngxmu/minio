# Cold Tier Mapping Recovery Test Plan

> Date: 2026-06-05
> Branch: `codex/cold-backup-tiering-test`
> Goal: verify whether a database-style mapping can recover transitioned objects from cold MinIO if the original source MinIO metadata is unavailable.

## 1. Purpose

MinIO lifecycle transition can free source disk space, but it is not a standalone disaster-recovery copy. The source MinIO metadata remains required for normal reads.

This test answers a narrower question:

```text
Can we record enough source-to-cold mapping data during transition to later restore objects from cold MinIO into a fresh MinIO under the original bucket/key?
```

## 2. Hypothesis

Expected behavior:

```text
source object transitions to cold MinIO
cold MinIO stores data under an internal generated key
source object metadata knows how to fetch that internal cold object
application code does not naturally know that cold key
```

Potential recovery path:

```text
record original source object metadata
discover newly created cold object key after transition
verify cold object can be read through cold MinIO S3 API
store verified mapping
restore cold object into a fresh MinIO under original bucket/key
verify checksum
```

Failure condition:

```text
If the cold object cannot be read through cold MinIO S3 API as one object, mapping-based recovery is not viable.
Do not attempt production recovery by manually reading part files from disk.
```

## 3. Test Topology

Use isolated services only:

| Role | Version | Endpoint | Purpose |
| --- | --- | --- | --- |
| source MinIO | `RELEASE.2022-11-08T05-27-07Z` | temporary port | simulate production source |
| cold MinIO | `RELEASE.2022-11-08T05-27-07Z` | temporary port | receive transitioned object |
| restore MinIO | `RELEASE.2022-11-08T05-27-07Z` | temporary port | fresh restore target |
| mapping DB | SQLite | local file | record source/cold mapping |

Do not use production data directories. Use fresh empty directories.

## 4. Mapping Schema

Prototype SQLite table:

```sql
CREATE TABLE cold_tier_object_mapping (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  source_bucket TEXT NOT NULL,
  source_key TEXT NOT NULL,
  source_version_id TEXT NOT NULL DEFAULT '',
  source_etag TEXT,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  content_type TEXT,
  user_metadata_json TEXT,
  tier_name TEXT NOT NULL,
  cold_endpoint_alias TEXT NOT NULL,
  cold_bucket TEXT NOT NULL,
  cold_prefix TEXT NOT NULL,
  cold_object_key TEXT,
  transition_time TEXT NOT NULL,
  verify_status TEXT NOT NULL,
  restore_status TEXT NOT NULL DEFAULT 'NOT_RESTORED',
  UNIQUE(source_id, source_bucket, source_key, source_version_id)
);
```

## 5. Test Steps

### Step 1: Start isolated MinIO services

```text
start source
start cold
start restore
configure mc aliases
create source bucket
create cold bucket
create restore bucket
```

### Step 2: Upload source object and record baseline

```text
upload one object to source bucket/key
record source stat
compute sha256 by reading from source S3 API
record content-type and user metadata
insert mapping row with verify_status=PENDING
```

### Step 3: Snapshot cold bucket before transition

```text
mc ls --recursive cold/coldbucket > cold-before.txt
```

### Step 4: Configure remote tier and transition

```text
mc ilm tier add minio source COLD_TEST ...
mc ilm rule add --prefix original/key --transition-days 0 --transition-tier COLD_TEST source/sourcebucket
wait until source stat shows X-Amz-Storage-Class or Storage Class COLD_TEST
```

### Step 5: Discover cold object key

```text
mc ls --recursive cold/coldbucket > cold-after.txt
diff cold-before.txt cold-after.txt
for each new object candidate:
  read object through cold S3 API
  compute sha256
  compare size and sha256 with source baseline
```

Pass condition:

```text
exactly one cold S3 object matches source size and sha256
```

If multiple candidates match, record all candidates and mark the test inconclusive.

### Step 6: Restore into fresh MinIO

```text
mc cat cold/coldbucket/<cold_object_key> | mc pipe restore/sourcebucket/original/key
mc stat restore/sourcebucket/original/key
mc cat restore/sourcebucket/original/key | sha256sum
```

Pass condition:

```text
restored object size equals source size
restored object sha256 equals source sha256
restored object can be read from restore MinIO using the original bucket/key
```

### Step 7: Simulate source metadata loss

```text
stop source MinIO
run recovery using only mapping DB and cold MinIO
restore into a new empty MinIO
verify checksum
```

This is the real acceptance test.

## 6. Acceptance Criteria

Mapping recovery is viable only if all conditions are true:

```text
source object transitions successfully
cold object key is discoverable through S3 listing
cold object is readable through S3 API as one object
cold object checksum equals source checksum
restore MinIO receives the object under original bucket/key
restored checksum equals source checksum
the workflow still passes when source MinIO is stopped
```

## 7. Production Implication

If this test passes, a DB mapping can become a recovery aid, but still needs:

```text
large-prefix restore drill
metadata preservation test
versioned object test if versioning is enabled
concurrent transition mapping test
duplicate size/checksum collision handling
monitoring and reconcile worker
```

If this test fails, the production architecture must use a separate supported DR layer:

```text
MinIO replication
or explicit archive copy to cold MinIO under original bucket/key
```

## 8. Preferred Production Direction

For business data where source metadata loss is unacceptable:

```text
Use MinIO transition for space relief.
Use independent replication or explicit archive copy for disaster recovery.
Do not call transition-only cold tier a cold backup.
```
