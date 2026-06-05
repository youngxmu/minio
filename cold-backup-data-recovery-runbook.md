# Cold Backup Data Recovery Runbook

> Date: 2026-06-05
> Branch: `codex/cold-backup-tiering-test`
> Scope: recovery from cold-tier MinIO data after old source MinIO metadata is unavailable.

## 1. Core Answer

Yes, the mapping relationship must be handled during migration.

It should not be postponed until after the old MinIO metadata is lost.

Reason:

```text
MinIO lifecycle transition keeps the original bucket/key metadata on the source MinIO.
The cold MinIO stores payload data under generated internal keys.
The cold internal key is not the original business key.
After source metadata loss, cold MinIO alone cannot reliably tell us:
  original source server
  original bucket
  original object key
  original version id
  original user metadata
```

Therefore:

```text
For capacity relief, transition is enough.
For recovery, generate and verify mapping rows during every transition wave.
```

## 2. Recovery Model

There are two realistic recovery modes.

### Mode A: Application Fallback

When a user requests an old object:

```text
1. Business code receives original source bucket/key.
2. It checks whether the old source MinIO can serve the object.
3. If not, it looks up the recovery mapping table.
4. It reads the mapped cold object from cold MinIO.
5. It streams bytes back to the user.
```

This mode avoids immediately rebuilding all objects, but requires application code changes and strong mapping coverage.

### Mode B: Rebuild New MinIO

When a source MinIO is lost or must be rebuilt:

```text
1. Prepare a fresh MinIO.
2. Read mapping rows for the affected source.
3. For each row, read cold_bucket/cold_object_key from cold MinIO.
4. Write the object to source_bucket/source_key in the fresh MinIO.
5. Restore content-type and user metadata where available.
6. Verify size and checksum.
7. Mark restore_status.
```

This mode recreates the original bucket/key namespace and is easier to reason about for a full recovery drill.

## 3. Mapping Table

Prototype schema:

```sql
CREATE TABLE cold_tier_object_mapping (
  id BIGINT PRIMARY KEY,
  source_id VARCHAR(64) NOT NULL,
  source_endpoint_alias VARCHAR(128) NOT NULL,
  business_video_id BIGINT NOT NULL,
  user_id BIGINT,
  file_role VARCHAR(64) NOT NULL,
  required_role BOOLEAN NOT NULL DEFAULT TRUE,
  source_bucket VARCHAR(255) NOT NULL,
  source_key TEXT NOT NULL,
  source_version_id VARCHAR(255) NOT NULL DEFAULT '',
  source_etag VARCHAR(255),
  size_bytes BIGINT NOT NULL,
  sha256 CHAR(64) NOT NULL,
  content_type VARCHAR(512),
  user_metadata_json JSON,
  last_modified DATETIME,
  tier_name VARCHAR(128) NOT NULL,
  cold_endpoint_alias VARCHAR(128) NOT NULL,
  cold_bucket VARCHAR(255) NOT NULL,
  cold_prefix TEXT NOT NULL,
  cold_object_key TEXT,
  transition_batch_id VARCHAR(128) NOT NULL,
  business_create_time DATETIME,
  business_update_time DATETIME,
  video_status VARCHAR(64),
  transition_time DATETIME,
  match_status VARCHAR(32) NOT NULL,
  verify_status VARCHAR(32) NOT NULL,
  restore_status VARCHAR(32) NOT NULL DEFAULT 'NOT_RESTORED',
  ambiguity_group_id VARCHAR(128),
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
);

CREATE UNIQUE INDEX uk_source_object
  ON cold_tier_object_mapping(source_id, source_bucket, source_key, source_version_id);

CREATE INDEX idx_business_video
  ON cold_tier_object_mapping(source_id, business_video_id, file_role);

CREATE INDEX idx_cold_object
  ON cold_tier_object_mapping(cold_endpoint_alias, cold_bucket, cold_object_key(255));

CREATE INDEX idx_batch_status
  ON cold_tier_object_mapping(transition_batch_id, verify_status, restore_status);
```

Recommended status values:

| Field | Values |
| --- | --- |
| `match_status` | `PENDING`, `EXACT`, `DUPLICATE_PAYLOAD`, `AMBIGUOUS`, `MISSING`, `FAILED` |
| `verify_status` | `PENDING`, `VERIFIED`, `FAILED` |
| `restore_status` | `NOT_RESTORED`, `RESTORED`, `RESTORE_FAILED` |

For MySQL versions that do not support indexed `TEXT` expressions directly, use prefix indexes or an additional hashed key column.

## 4. Migration-Time Mapping Workflow

Run this workflow per controlled batch.

### Step 1: Build Source Manifest

Before adding the lifecycle transition rule, record:

```text
source_id
source endpoint alias
business videoId
user id
file role
required or optional role
source bucket
source key
version id if enabled
size
ETag
SHA256
content-type
user metadata
last modified
business create/update time
video status
batch id
```

The checksum should be computed through the source MinIO S3 API, not by reading MinIO disk part files.

Business rule:

```text
Use time to select candidate videoId rows from the business database.
Do not use MinIO object age as the direct business migration rule.
For each selected videoId, resolve the expected object roles before transition:
  source_upload
  cover
  watermark_source
  transcoded_video
  playback_video
```

Rows with missing required roles should be marked `PARTIAL` and skipped in the first production waves.

### Step 2: Snapshot Cold Prefix Before

Record all existing objects under the assigned cold bucket/prefix:

```text
cold endpoint alias
cold bucket
cold prefix
cold object key
size
last modified
```

This prevents old cold objects from being confused with newly transitioned objects.

### Step 3: Transition A Controlled Batch

Use a narrow lifecycle rule:

```text
one source server
one source bucket
one videoId group, videoId prefix, or bounded object set
one transition batch id
```

Remove the batch lifecycle rule after transition completes. Keep the remote tier configuration and credentials because source reads still depend on them.

### Step 4: Snapshot Cold Prefix After

List the same cold bucket/prefix again and diff against the before snapshot.

The newly appeared cold objects are candidate targets for mapping rows.

### Step 5: Verify Cold Candidates

For every candidate cold object:

```text
read through cold MinIO S3 API
compute size
compute SHA256
compare with source manifest
```

Do not reconstruct bytes from `part.1`, `xl.meta`, or MinIO data directories.

### Step 6: Reconcile

Match source rows to cold candidates:

```text
exactly one source row and one cold candidate with same size + sha256:
  match_status = EXACT

multiple source rows with identical payload and matching cold candidates:
  match_status = DUPLICATE_PAYLOAD
  recovery can restore bytes correctly, but strict object-to-object audit needs a tie-breaker

no matching cold candidate:
  match_status = MISSING

multiple different cold candidates cannot be deterministically assigned:
  match_status = AMBIGUOUS
```

The 2026-06-05 A380 prefix test hit this real case:

```text
Two JPG objects had identical size and SHA256.
Both can be restored byte-correctly.
They are ambiguous for strict one-to-one mapping unless extra metadata or wave ordering is used.
```

### Step 7: Store And Freeze Batch Result

Before expanding the migration:

```text
all rows must be VERIFIED, DUPLICATE_PAYLOAD with accepted policy, or explicitly excluded
store lifecycle rule id and tier name
store source and cold manifest paths
store restore drill result
record unresolved rows as blockers
```

## 5. Duplicate Payload Handling

Duplicate content is normal in media systems: covers, thumbnails, repeated uploads, and copied videos may produce identical bytes.

Recommended policy:

```text
For byte recovery:
  duplicate payload mapping is acceptable if size and SHA256 match.

For strict audit or metadata recovery:
  do not rely only on size + SHA256.
  add one of:
    object version id
    source last-modified window
    batch sub-wave ordering
    source metadata fingerprint
    explicit archive copy under original key
```

If the production recovery requirement is strict original object lineage, prefer explicit archive copy or supported replication.

## 6. Restore Drill

A batch is not complete until a restore drill passes.

Minimum drill:

```text
1. Create a fresh restore MinIO.
2. Select at least one exact row and one duplicate-payload row if present.
3. Read cold_bucket/cold_object_key from cold MinIO.
4. Write source_bucket/source_key to restore MinIO.
5. Verify size and SHA256.
6. Confirm restored object is reachable through the original bucket/key path on restore MinIO.
```

For larger waves:

```text
restore at least one complete videoId group
restore at least one sample per source prefix if multiple prefixes are involved
restore the largest objects
restore recently transitioned objects
restore duplicate payload objects
restore objects with custom metadata if present
```

Complete videoId restore acceptance:

```text
all required file roles for the selected videoId are restored
each restored role has the original bucket/key
each restored role passes size and SHA256 verification
the restored videoId can be evaluated as a complete business unit
optional missing roles are explicitly documented
```

## 7. Failure Handling

If mapping reconciliation fails:

```text
stop expanding the lifecycle wave
remove or disable the new lifecycle rule
keep cold target data intact
keep source tier configuration intact
sample read source objects through old MinIO
inspect source and cold MinIO logs
do not delete source stubs or cold internal objects
```

If source metadata is already lost and mapping was not generated:

```text
do not promise full original bucket/key recovery from cold MinIO alone
attempt forensic analysis only as a separate emergency project
prefer restoring from replication, explicit archive, or other backups
```

## 8. Production Recommendation

Use three layers where risk requires it:

```text
Layer 1: MinIO transition
  purpose: free old source disks while old URLs keep working

Layer 2: mapping table and restore worker
  purpose: custom recovery aid and rebuild drill

Layer 3: supported backup, replication, or explicit archive copy
  purpose: authoritative disaster recovery if old source metadata loss is unacceptable
```

Minimum rule:

```text
No migration batch is production-complete until its mapping rows and restore drill are complete.
```
