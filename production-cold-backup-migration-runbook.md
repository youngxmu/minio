# Production Cold Backup MinIO Migration Runbook

> Date: 2026-06-08
> Branch: `codex/cold-backup-tiering-test`
> Scope: production execution manual for moving old independent MinIO payload data to a cold-backup MinIO with MinIO lifecycle transition.

## 1. Purpose

This runbook is the production execution version of the cold-backup migration plan.

Target behavior:

```text
old MinIO source keeps the original host/bucket/key and small metadata/stub
object payload moves to the cold MinIO tier bucket
business reads still use the old MinIO URL
source disk space is released after transition completes
mapping rows are generated during migration for recovery drills
```

This is a capacity relief plan, not a complete disaster-recovery replacement.

Do not use this runbook to:

```text
move files manually inside MinIO data directories
switch business URLs directly to cold-tier internal keys
delete cold-tier bucket contents directly
claim recovery after source metadata loss without a mapping restore drill
run broad full-bucket lifecycle rules as the first production action
```

## 2. Current Evidence

Validated in tests:

| Date | Result | Evidence |
| --- | --- | --- |
| 2026-06-04 | MinIO lifecycle transition moved real A380 object payload to 4070S cold MinIO and source URL stayed readable | `cold-backup-tiering-results-2026-06-04.md` |
| 2026-06-04 | Same-version MinIO `RELEASE.2022-11-08T05-27-07Z` source-to-cold transition passed in isolated test | `minio-tier-version-compat-results-2026-06-04.md` |
| 2026-06-05 | `videoId=14708948` five-file business unit transitioned, mapped, and restored | `videoid-cold-backup-smoke-results-2026-06-05.md` |
| 2026-06-08 | Source-side delete of an already-transitioned object also removed the cold internal object in the tested unversioned path | `cold-backup-delete-smoke-results-2026-06-08.md` |

Production implication:

```text
First production wave should use the same MinIO release on source and cold target.
For current production-main MinIO, use RELEASE.2022-11-08T05-27-07Z on both sides until another exact version mix is tested.
```

## 3. Roles And Naming

Use stable source ids. Do not use raw IP addresses as the only identifier in batch records.

Example:

| Role | Example |
| --- | --- |
| Source id | `oldminio1` |
| Source alias | `old1` |
| Source bucket | `sucaiwang` |
| Cold alias | `cold1` |
| Cold bucket | `tier-oldminio1-sucaiwang` |
| Cold prefix | `oldminio1/sucaiwang/` |
| Tier name | `COLD_OLDMINIO1_SUCAIWANG` |
| Batch id | `oldminio1-sucaiwang-smoke-20260608-001` |

Bucket isolation rule:

```text
oldminio1/sucaiwang -> tier-oldminio1-sucaiwang
oldminio2/sucaiwang -> tier-oldminio2-sucaiwang
```

Do not let two old independent MinIO sources write cold-tier objects into the same cold bucket/prefix without a source-specific namespace.

## 4. Production Prerequisites

### 4.1 Change Window

Before touching production:

- [ ] Confirm a low-traffic migration window.
- [ ] Assign one operator and one reviewer.
- [ ] Confirm source MinIO owner and business owner for the smoke object.
- [ ] Confirm stop conditions and who can stop the wave.
- [ ] Confirm no one will manually clean the cold-tier bucket during the wave.
- [ ] Confirm credentials are available through a private channel, not this repo.

### 4.2 Version And Tooling

Required:

```text
source MinIO version recorded
cold MinIO version recorded
source and cold versions aligned for the wave
management mc version recorded
mc supports ilm tier and ilm rule command families
jq is installed on the management host
```

Commands:

```bash
minio --version

MC=/opt/minio-tools/mc
$MC --version
$MC admin info old1
$MC admin info cold1
$MC ilm tier ls old1
$MC ilm rule ls old1/sucaiwang
```

For current production-main source release:

```text
RELEASE.2022-11-08T05-27-07Z
```

Use a cold target with the same MinIO release for the first production validation wave.

### 4.3 Source Inventory

Record one sheet row per source MinIO:

| Field | Required |
| --- | --- |
| source id | yes |
| endpoint | yes |
| MinIO version | yes |
| service type | systemd or Docker |
| data paths | all data disks or volumes |
| bucket list | yes |
| current lifecycle export | yes |
| current remote tier list | yes |
| disk usage and inode usage | yes |
| top large prefixes | recommended |
| versioning/object-lock status | required before delete tests |

Minimum command set:

```bash
$MC admin info old1
$MC ls old1
$MC ilm tier ls old1
$MC ilm rule ls old1/sucaiwang
$MC ilm rule export old1/sucaiwang > old1-sucaiwang-lifecycle-before.xml
df -h
df -i
```

If bucket versioning, object lock, legal hold, or retention is enabled, do not assume the 2026-06-08 delete smoke covers that bucket. Run a dedicated delete/versioning smoke first.

### 4.4 Cold Target Readiness

Cold target requirements:

```text
same MinIO release as source for the first wave
enough free capacity for target payload plus overhead plus 20% headroom
dedicated data disks or mount paths
health endpoint returns ready
dedicated access key for source tiering
no user-facing traffic in cold-tier buckets
```

Required cold-tier permissions:

```text
s3:PutObject
s3:GetObject
s3:DeleteObject
s3:ListBucket
s3:GetBucketLocation
s3:AbortMultipartUpload
s3:ListBucketMultipartUploads
s3:ListMultipartUploadParts
```

Do not disable or rotate the tier credentials while transitioned objects still exist. Source reads depend on those credentials.

## 5. Environment Template

Use one management host that can reach both old MinIO and cold MinIO.

Do not paste secrets into shell history on shared hosts. Load them from a private file or secret manager.

```bash
export MC=/opt/minio-tools/mc

export SOURCE_ID=oldminio1
export SOURCE_ALIAS=old1
export SOURCE_ENDPOINT=http://oldminio1.internal:9000
export SOURCE_BUCKET=sucaiwang
export SOURCE_ACCESS_KEY='<from-private-secret-store>'
export SOURCE_SECRET_KEY='<from-private-secret-store>'

export COLD_ALIAS=cold1
export COLD_ENDPOINT=http://coldminio1.internal:9000
export COLD_BUCKET=tier-oldminio1-sucaiwang
export COLD_PREFIX=oldminio1/sucaiwang/
export TIER_NAME=COLD_OLDMINIO1_SUCAIWANG

export COLD_ACCESS_KEY='<from-private-secret-store>'
export COLD_SECRET_KEY='<from-private-secret-store>'
```

Alias setup:

```bash
$MC alias set "${SOURCE_ALIAS}" "${SOURCE_ENDPOINT}" "${SOURCE_ACCESS_KEY}" "${SOURCE_SECRET_KEY}"
$MC alias set "${COLD_ALIAS}" "${COLD_ENDPOINT}" "${COLD_ACCESS_KEY}" "${COLD_SECRET_KEY}"
```

## 6. Phase A - One Small File Smoke

Run this before any business-object migration. Use two new small objects:

```text
verify.bin: transition and keep readable for manual verification
delete.bin: transition and then delete through source to verify cold cleanup
```

### 6.1 Create Isolated Smoke Objects

```bash
export BATCH_ID="${SOURCE_ID}-${SOURCE_BUCKET}-smallfile-$(date +%Y%m%d-%H%M%S)"
export SMOKE_PREFIX="migration-smoke/${BATCH_ID}"
export VERIFY_KEY="${SMOKE_PREFIX}/verify.bin"
export DELETE_KEY="${SMOKE_PREFIX}/delete.bin"

mkdir -p "./${BATCH_ID}"
dd if=/dev/urandom of="./${BATCH_ID}/verify.bin" bs=1M count=8
dd if=/dev/urandom of="./${BATCH_ID}/delete.bin" bs=1M count=8
sha256sum "./${BATCH_ID}/verify.bin" "./${BATCH_ID}/delete.bin" > "./${BATCH_ID}/source-sha256.txt"

$MC cp "./${BATCH_ID}/verify.bin" "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${VERIFY_KEY}"
$MC cp "./${BATCH_ID}/delete.bin" "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${DELETE_KEY}"
```

Verify source read before transition:

```bash
$MC stat "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${VERIFY_KEY}"
$MC stat "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${DELETE_KEY}"
$MC cat "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${VERIFY_KEY}" | sha256sum
$MC cat "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${DELETE_KEY}" | sha256sum
```

### 6.2 Configure Cold Tier

Create the cold bucket once per source bucket:

```bash
$MC mb -p "${COLD_ALIAS}/${COLD_BUCKET}"
```

Add the remote tier on the source:

```bash
$MC ilm tier add minio "${SOURCE_ALIAS}" "${TIER_NAME}" \
  --endpoint "${COLD_ENDPOINT}" \
  --access-key "${COLD_ACCESS_KEY}" \
  --secret-key "${COLD_SECRET_KEY}" \
  --bucket "${COLD_BUCKET}" \
  --prefix "${COLD_PREFIX}" \
  --storage-class STANDARD
```

Validate:

```bash
$MC ilm tier ls "${SOURCE_ALIAS}"
$MC ilm tier info "${SOURCE_ALIAS}" "${TIER_NAME}"
$MC ilm tier check "${SOURCE_ALIAS}" "${TIER_NAME}"
```

If the tier already exists, do not recreate it. Verify its endpoint, bucket, and prefix match the implementation sheet.

### 6.3 Add Narrow Lifecycle Rule

Only target the smoke prefix:

```bash
$MC ilm rule add "${SOURCE_ALIAS}/${SOURCE_BUCKET}" \
  --prefix "${SMOKE_PREFIX}/" \
  --transition-days 0 \
  --transition-tier "${TIER_NAME}"

$MC ilm rule export "${SOURCE_ALIAS}/${SOURCE_BUCKET}" > "./${BATCH_ID}/lifecycle-after-smoke-rule.json"

export SMOKE_RULE_ID="$(jq -r \
  --arg prefix "${SMOKE_PREFIX}/" \
  --arg tier "${TIER_NAME}" \
  '.Rules[] | select(.Filter.Prefix == $prefix and .Transition.StorageClass == $tier) | .ID' \
  "./${BATCH_ID}/lifecycle-after-smoke-rule.json")"
test -n "${SMOKE_RULE_ID}"
```

If the selected `mc` exports XML instead of JSON, record the equivalent rule id from `mc ilm rule ls` or the XML export before continuing.

### 6.4 Wait For Actual Transition

Rule creation is not completion. Poll until both objects show the cold tier storage class.

```bash
while true; do
  date
  $MC stat --json "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${VERIFY_KEY}" | jq -r '.metadata."X-Amz-Storage-Class" // .storageClass // "STANDARD"'
  $MC stat --json "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${DELETE_KEY}" | jq -r '.metadata."X-Amz-Storage-Class" // .storageClass // "STANDARD"'
  sleep 30
done
```

Expected:

```text
COLD_OLDMINIO1_SUCAIWANG
COLD_OLDMINIO1_SUCAIWANG
```

Also verify source read still works:

```bash
$MC cat "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${VERIFY_KEY}" | sha256sum
$MC cat "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${DELETE_KEY}" | sha256sum
```

### 6.5 Verify Cold Payload

Snapshot the cold prefix and find the new cold objects:

```bash
$MC ls --recursive --json "${COLD_ALIAS}/${COLD_BUCKET}/${COLD_PREFIX}" > "./${BATCH_ID}/cold-after.jsonl"
jq -r --arg prefix "${COLD_PREFIX}" 'select(.type == "file") | $prefix + .key' \
  "./${BATCH_ID}/cold-after.jsonl" \
  > "./${BATCH_ID}/cold-candidate-keys.txt"
```

For the small-file smoke, match candidates by size and SHA256:

```bash
VERIFY_SHA="$(sha256sum "./${BATCH_ID}/verify.bin" | awk '{print $1}')"
DELETE_SHA="$(sha256sum "./${BATCH_ID}/delete.bin" | awk '{print $1}')"
: > "./${BATCH_ID}/cold-mapping.tsv"

while read -r cold_key; do
  cold_sha="$($MC cat "${COLD_ALIAS}/${COLD_BUCKET}/${cold_key}" | sha256sum | awk '{print $1}')"
  cold_size="$($MC stat --json "${COLD_ALIAS}/${COLD_BUCKET}/${cold_key}" | jq -r '.size')"
  if [ "${cold_sha}" = "${VERIFY_SHA}" ]; then
    printf 'verify\t%s\t%s\t%s\n' "${cold_key}" "${cold_size}" "${cold_sha}" >> "./${BATCH_ID}/cold-mapping.tsv"
  elif [ "${cold_sha}" = "${DELETE_SHA}" ]; then
    printf 'delete\t%s\t%s\t%s\n' "${cold_key}" "${cold_size}" "${cold_sha}" >> "./${BATCH_ID}/cold-mapping.tsv"
  fi
done < "./${BATCH_ID}/cold-candidate-keys.txt"

VERIFY_COLD_KEY="$(awk -F '\t' '$1 == "verify" {print $2}' "./${BATCH_ID}/cold-mapping.tsv")"
DELETE_COLD_KEY="$(awk -F '\t' '$1 == "delete" {print $2}' "./${BATCH_ID}/cold-mapping.tsv")"
test -n "${VERIFY_COLD_KEY}"
test -n "${DELETE_COLD_KEY}"
```

Acceptance:

```text
verify.bin source SHA256 equals one cold object SHA256
delete.bin source SHA256 equals one cold object SHA256
source stat shows cold tier storage class
source read still returns original bytes
```

### 6.6 Delete Smoke

Delete only `delete.bin`, and only through the source old MinIO:

```bash
$MC rm "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${DELETE_KEY}"
```

Verify:

```bash
$MC stat "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${DELETE_KEY}" || echo "source delete verified"
$MC stat "${COLD_ALIAS}/${COLD_BUCKET}/${DELETE_COLD_KEY}" || echo "cold delete verified"
$MC stat "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${VERIFY_KEY}"
$MC stat "${COLD_ALIAS}/${COLD_BUCKET}/${VERIFY_COLD_KEY}"
```

Acceptance:

```text
delete.bin is gone from source
delete.bin cold internal object is gone
verify.bin remains readable from source
verify.bin remains readable from cold
```

If cold internal object remains after source delete, stop the wave and investigate versioning, object-lock, credential, or lifecycle behavior.

### 6.7 Smoke Cleanup

Remove only the batch lifecycle rule:

```bash
$MC ilm rule rm "${SOURCE_ALIAS}/${SOURCE_BUCKET}" --id "${SMOKE_RULE_ID}"
$MC ilm rule export "${SOURCE_ALIAS}/${SOURCE_BUCKET}" > "./${BATCH_ID}/lifecycle-after-cleanup.json"
```

Keep the remote tier and tier credentials if `verify.bin` or later transitioned objects still exist.

After manual validation, delete `verify.bin` through source:

```bash
$MC rm "${SOURCE_ALIAS}/${SOURCE_BUCKET}/${VERIFY_KEY}"
```

Do not delete cold-tier bucket objects directly.

## 7. Phase B - One Business VideoId Smoke

After the small-file smoke passes, run one real business `videoId` group.

Use the business database to select the videoId. Do not select directly by MinIO object age.

Resolve and verify expected roles:

| Role | Required first wave |
| --- | --- |
| `source_upload` | yes |
| `cover` | yes if business page depends on it |
| `watermark_source` | yes |
| `transcoded_video` | yes |
| `playback_video` | yes |

Before transition, create a source manifest:

```text
transition_batch_id
source_id
business_video_id
user_id
file_role
source_bucket
source_key
size_bytes
etag
sha256
content_type
last_modified
business_create_time
business_update_time
video_status
```

Classify:

| Status | Action |
| --- | --- |
| `COMPLETE` | eligible |
| `PARTIAL` | skip first waves |
| `ACTIVE` | skip |
| `UNKNOWN_LAYOUT` | investigate |
| already cold tier | skip and record existing mapping |

If all selected objects share a safe prefix, use that prefix. Otherwise, use exact-key rules for the small smoke and record every rule id.

Acceptance:

```text
all required roles exist before transition
all selected objects transition to the expected cold tier
source URLs still return bytes after transition
source disk footprint shrinks to metadata/stub scale
cold bucket grows by approximately payload size
mapping rows match cold internal keys by size and SHA256
one restore drill writes the objects into a fresh MinIO under original bucket/key
batch lifecycle rules are removed after completion
```

## 8. Phase C - Controlled Production Wave

Only start this phase after:

```text
small-file smoke passed
one business videoId smoke passed
mapping restore drill passed
delete smoke passed for the exact bucket settings
```

First production wave shape:

```text
one old source MinIO
one bucket
one cold target bucket/prefix
10 to 100 COMPLETE videoId rows
low business traffic window
one migration operator and one reviewer
```

Wave flow:

1. Export current lifecycle rules and tier config.
2. Generate videoId source manifest from the business database.
3. HEAD and checksum all required source objects.
4. Skip `PARTIAL`, `ACTIVE`, `UNKNOWN_LAYOUT`, and already-cold rows.
5. Snapshot cold bucket/prefix before transition.
6. Add narrow lifecycle rules for the batch.
7. Monitor until storage class changes and source footprint shrinks.
8. Snapshot cold bucket/prefix after transition.
9. Build mapping rows by before/after cold diff plus size/SHA256 match.
10. Verify source reads for samples and large objects.
11. Restore at least one complete videoId group into a fresh MinIO.
12. Remove batch lifecycle rules.
13. Mark batch complete only after mapping and restore pass.

Do not expand more than one dimension per wave:

```text
source count
bucket count
videoId count
business age window
prefix count
```

## 9. Monitoring During A Wave

Check every 5 to 15 minutes:

| Area | Check |
| --- | --- |
| Source health | readiness endpoint, `mc admin info`, process logs |
| Cold health | readiness endpoint, `mc admin info`, process logs |
| Lifecycle | rule export, storage class count, transition logs |
| Source disk | `df -h`, object footprint sample, inode usage |
| Cold disk | `df -h`, bucket growth, inode usage |
| Access | source URL HEAD/GET samples |
| Mapping | exact, duplicate, ambiguous, missing, failed rows |
| Business | read latency and error reports |

Stop immediately if any of these occur:

```text
source read failures for transitioned objects
cold target write/read errors
Bad sha256 or transition failure logs
unexpected lifecycle rule scope
mapping mismatch or missing cold objects
cold target free capacity below agreed threshold
business error rate or latency exceeds agreed threshold
scanner transitions unrelated prefixes
```

## 10. Repeat Migration And Idempotency

Before adding rules for a new wave, stat every candidate object:

| Source object state | Action |
| --- | --- |
| `STANDARD` | eligible for this wave |
| current wave tier | already done, verify mapping |
| older cold tier | skip, keep original cold mapping |
| missing | mark missing and skip |
| active/recently updated | skip |

Do not migrate already-transitioned objects again. They are already source metadata/stubs and do not release meaningful additional source space.

## 11. Delete And Expiry

Business deletes for transitioned objects must go through the source old MinIO bucket/key.

Validated unversioned behavior:

```text
source delete -> source URL 404
source delete -> cold internal object 404
```

Production rule:

```text
delete expired business data through source MinIO
verify source object is gone
verify cold internal object is gone
mark mapping row DELETED
```

Forbidden:

```text
directly deleting cold internal objects
putting independent lifecycle expiration rules on cold-tier buckets
manual filesystem cleanup under cold MinIO data paths
```

If users ask to free cold target space, delete expired business objects through the source old MinIO, not through the cold MinIO bucket.

## 12. Mapping And Recovery

Mapping is required during migration, not after a failure.

Minimum mapping statuses:

| State | Meaning |
| --- | --- |
| `PENDING` | source manifest row exists, transition not verified |
| `VERIFIED` | source row matched a cold object by size and SHA256 |
| `DUPLICATE_PAYLOAD` | multiple source rows share identical payload |
| `AMBIGUOUS` | cold candidate cannot be mapped one-to-one |
| `RESTORED` | restore drill passed |
| `DELETED` | source and cold objects are both gone |
| `BROKEN_COLD_REFERENCE` | cold object deleted directly while source metadata remains |

Recovery drill must prove:

```text
read cold internal object through S3 API
write it into a fresh MinIO under original bucket/key
preserve content-type and important metadata where available
verify size and SHA256
verify restored URL can be read
```

See `cold-backup-data-recovery-runbook.md` for schema and recovery details.

## 13. Rollback And Safe Stop

Safe stop for a wave:

```bash
$MC ilm rule ls "${SOURCE_ALIAS}/${SOURCE_BUCKET}" --transition
$MC ilm rule rm "${SOURCE_ALIAS}/${SOURCE_BUCKET}" --id "${BATCH_RULE_ID}"
$MC ilm rule export "${SOURCE_ALIAS}/${SOURCE_BUCKET}" > "./${BATCH_ID}/lifecycle-after-stop.json"
```

Rules:

```text
remove or disable only the batch lifecycle rules
keep the remote tier configuration
keep cold-tier credentials valid
keep already transitioned cold payload intact
do not delete cold target data during an incident
do not promise a quick global rehydration
```

For already transitioned objects, normal reads should continue through source old MinIO as long as source metadata and cold target are healthy.

Rehydration must be a separate tested plan, not an emergency improvisation.

## 14. Completion Criteria

A production wave is complete only when all are true:

- [ ] Source and cold versions were recorded.
- [ ] Lifecycle rules before and after were archived.
- [ ] All intended candidate videoId rows have manifest rows.
- [ ] All migrated source objects show expected cold storage class.
- [ ] Source-space release was measured.
- [ ] Cold bucket growth was measured.
- [ ] Source URL samples return bytes after transition.
- [ ] Mapping rows are reconciled.
- [ ] Ambiguous rows have documented handling.
- [ ] Restore drill passed for at least one complete videoId group.
- [ ] Batch lifecycle rules were removed.
- [ ] Stop/rollback notes were recorded.

## 15. First Production Trial Recommendation

Recommended first trial:

```text
one production-like source MinIO running RELEASE.2022-11-08T05-27-07Z
one same-version cold MinIO target
one source bucket
two new 8 MiB smoke files
one delete smoke object
one retained smoke object for manual URL validation
one complete low-risk videoId group after small-file smoke passes
```

Do not start with a one-year age rule. Use the business database to select one safe videoId group first, then expand to 10 to 100 complete videoId rows only after the full smoke and restore checks pass.
