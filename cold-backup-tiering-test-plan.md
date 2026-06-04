# Cold Backup MinIO Tiering Test Plan

> Date: 2026-06-04
> Branch: `codex/cold-backup-tiering-test`
> Purpose: validate whether old independent MinIO servers can free local HDD space by transitioning historical object data to a new cold-backup MinIO while keeping source-side metadata and normal user access.

## 1. Technical Direction Verdict

The direction is reasonable if it is implemented as MinIO object tiering / lifecycle transition:

```text
old MinIO keeps bucket/object metadata
old MinIO transitions object data to remote cold MinIO
user/application still reads through old MinIO with the same bucket/key
old MinIO retrieves transitioned object data from cold MinIO on demand
```

This is not the same as manually moving data files out of the MinIO data directory.
Manual movement can break erasure metadata and object layout. The supported direction is to configure a remote tier and lifecycle transition rule, then let MinIO move the object.

Official references:

```text
Object tiering to remote MinIO:
https://docs.min.io/aistor/administration/object-lifecycle-management/object-tiering/transition-objects-to-minio/

Remote tier creation:
https://docs.min.io/aistor/reference/cli/mc-ilm-tier/mc-ilm-tier-add/

Lifecycle rule creation:
https://docs.min.io/aistor/reference/cli/mc-ilm-rule/mc-ilm-rule-add/
```

Important boundary:

```text
The cold MinIO is not an independent disaster-recovery copy for the old MinIO metadata.
The source MinIO metadata and the cold-tier object data are strongly linked.
If the source MinIO metadata is lost, the cold tier cannot be used by itself to restore the original source object namespace.
All reads for transitioned objects must continue to go through the source MinIO S3 API.
```

So this solves:

```text
free old MinIO disks
increase write headroom on old independent MinIO servers
keep historical data readable through the original host/bucket/key
```

It does not solve by itself:

```text
source MinIO disaster recovery
direct user reads from cold MinIO
removing the old MinIO service entirely
```

## 2. Production Fit For N Independent MinIO Servers

Current production model:

```text
business code chooses one of N independent MinIO servers for writes
each MinIO has independent buckets and independent local disks
some or all old MinIO servers are close to full
```

Recommended production mapping:

```text
one shared cold MinIO cluster can serve many old MinIO sources
but each source should get isolated cold-tier buckets or namespaces
```

Example:

| Source MinIO | Source bucket | Cold target bucket |
| --- | --- | --- |
| old1 | `sucaiwang` | `tier-old1-sucaiwang` |
| old2 | `sucaiwang` | `tier-old2-sucaiwang` |
| old3 | `legacy-b` | `tier-old3-legacy-b` |

Reason:

```text
old MinIO servers are independent and may contain identical bucket/key paths.
Using one isolated cold bucket per source bucket avoids collisions and makes rollback/accounting clearer.
The cold-tier data should not be manually edited, listed as user-facing storage, or shared with other writers.
```

## 3. Test Goal

Use A380 original MinIO data as the source and 4070S as the cold-backup MinIO target.

Single-object success means:

```text
1. Select one real video object from A380 original MinIO.
2. Record its logical size and physical disk footprint on A380.
3. Configure 4070S cold MinIO on HDD.
4. Configure A380 MinIO remote tier to 4070S cold MinIO.
5. Add a lifecycle transition rule that only targets that one object or a single-object prefix.
6. Wait until the object transitions.
7. Show A380 physical footprint shrinks to metadata/stub scale.
8. Show 4070S cold MinIO physical footprint increases by roughly the object size.
9. Read the object from the original A380 URL and verify the bytes/checksum still match.
10. Capture evidence that the read flows through 4070S cold MinIO.
```

## 4. Test Topology

| Role | Server | Endpoint | Storage |
| --- | --- | --- | --- |
| Source old MinIO | A380 `172.16.100.132` | `http://172.16.100.132:9000` | 4 x 15T HDD, restored systemd MinIO |
| Cold backup MinIO | 4070S `172.16.100.217` | proposed `http://172.16.100.217:19500` | HDD path `/data/data2/cold-backup-minio-test` |
| Console for cold backup | 4070S `172.16.100.217` | proposed `http://172.16.100.217:19590` | same |

Why not use 4070S existing `9000/9090`:

```text
4070S already has Docker minio_local on 9000/9090.
For this test, use an isolated cold MinIO instance on 19500/19590 to avoid disturbing other services.
```

Why use `/data/data2`:

```text
4070S /data/data2 is an HDD with about 11T available.
It is suitable for cold backup and makes space movement visible.
```

## 5. Pre-Checks

### A380 source

Verify source service:

```bash
curl -sS -i http://172.16.100.132:9000/minio/health/ready
systemctl is-active minio-local.service
df -hT /data/data1 /data/data2 /data/data3 /data/data4
```

Check lifecycle noise:

```bash
journalctl -u minio-local.service --since '1 hour ago' | grep -i transition
```

If existing COLD transition rules are still retrying, either document them as background noise or disable unrelated lifecycle rules before the test.

### 4070S cold target

Verify target disk:

```bash
df -hT /data/data2
mkdir -p /data/data2/cold-backup-minio-test/data
```

Start isolated cold MinIO:

```bash
docker run -d --name minio_cold_backup_test \
  -p 19500:9000 \
  -p 19590:9090 \
  -e MINIO_ROOT_USER="$COLD_MINIO_ROOT_USER" \
  -e MINIO_ROOT_PASSWORD="$COLD_MINIO_ROOT_PASSWORD" \
  -v /data/data2/cold-backup-minio-test/data:/data \
  minio/minio:RELEASE.2025-09-07T16-13-09Z \
  server /data --console-address :9090
```

Use the same MinIO version as A380 if possible:

```text
A380 current MinIO: RELEASE.2025-09-07T16-13-09Z
```

## 6. Select One Video Object

Selection requirements:

```text
real object from A380 original MinIO
video-like extension or known video content
large enough to show disk movement, preferably >= 100MB
not a currently active user upload
not under a prefix that will match many objects accidentally
```

Candidate selection methods:

```bash
# Prefer S3 listing when a healthy mc binary is available.
mc find a380/sucaiwang --name '*.mp4' --name '*.mov' --name '*.m3u8' --name '*.ts' --larger 100MiB

# Fallback: inspect MinIO disk layout read-only, then verify by S3 HEAD.
find /data/data1/sucaiwang -type d \
  | grep -Ei '\\.(mp4|mov|m4v|ts)$' \
  | head
```

Record:

```text
SOURCE_BUCKET=
SOURCE_KEY=
LOGICAL_SIZE_BYTES=
SOURCE_ETAG=
SOURCE_SHA256_SAMPLE_OR_FULL=
```

## 7. Baseline Space Measurement

Record source object footprint across all A380 erasure disks:

```bash
for n in 1 2 3 4; do
  du -sb "/data/data$n/${SOURCE_BUCKET}/${SOURCE_KEY}" 2>/dev/null || true
done
df -B1 /data/data1 /data/data2 /data/data3 /data/data4
```

Record target footprint:

```bash
du -sb /data/data2/cold-backup-minio-test/data
df -B1 /data/data2
```

Record baseline read:

```bash
mc stat "a380/${SOURCE_BUCKET}/${SOURCE_KEY}"
mc cat "a380/${SOURCE_BUCKET}/${SOURCE_KEY}" | sha256sum
```

If `mc` is unavailable, use a signed S3 GET/HEAD script.

## 8. Configure Cold Tier

Set aliases from a machine with a healthy `mc`:

```bash
mc alias set a380 http://172.16.100.132:9000 "$A380_ACCESS_KEY" "$A380_SECRET_KEY"
mc alias set cold4070 http://172.16.100.217:19500 "$COLD_MINIO_ROOT_USER" "$COLD_MINIO_ROOT_PASSWORD"
```

Create cold bucket:

```bash
mc mb cold4070/tier-a380-sucaiwang
```

Add cold remote tier to A380:

```bash
mc ilm tier add minio a380 COLD4070-A380 \
  --endpoint http://172.16.100.217:19500 \
  --access-key "$COLD_MINIO_ROOT_USER" \
  --secret-key "$COLD_MINIO_ROOT_PASSWORD" \
  --bucket tier-a380-sucaiwang
```

Check tier:

```bash
mc ilm tier ls a380
mc ilm tier check a380 COLD4070-A380
```

## 9. Add Single-Object Transition Rule

Use a prefix that targets only the selected object:

```bash
mc ilm rule add "a380/${SOURCE_BUCKET}" \
  --prefix "${SOURCE_KEY}" \
  --transition-days 0 \
  --transition-tier COLD4070-A380
```

Important:

```text
Do not add an expiration rule.
Do not delete the source object.
The source object must remain logically present so old URLs keep working.
```

List rule:

```bash
mc ilm rule ls "a380/${SOURCE_BUCKET}"
```

## 10. Wait For Transition

Lifecycle transition is asynchronous. Poll until one of these indicates transition completed:

```bash
mc stat "a380/${SOURCE_BUCKET}/${SOURCE_KEY}"
mc ilm restore status "a380/${SOURCE_BUCKET}/${SOURCE_KEY}" 2>/dev/null || true
```

Also watch MinIO logs:

```bash
journalctl -u minio-local.service -f
```

Space polling:

```bash
watch -n 30 '
  echo A380 source;
  for n in 1 2 3 4; do du -sb /data/data$n/${SOURCE_BUCKET}/${SOURCE_KEY} 2>/dev/null || true; done;
  echo 4070 cold;
  ssh root@172.16.100.217 "du -sb /data/data2/cold-backup-minio-test/data"
'
```

## 11. Prove Data Flow On Read

After transition, run a read through the original A380 endpoint:

```bash
mc cat "a380/${SOURCE_BUCKET}/${SOURCE_KEY}" > /tmp/cold-tier-read-video
sha256sum /tmp/cold-tier-read-video
```

In parallel, capture cold target traffic:

```bash
# On 4070S
tcpdump -i any host 172.16.100.132 and port 19500
```

Optional S3 trace if supported by the client and server:

```bash
mc admin trace cold4070 --type s3
```

Expected evidence:

```text
A380 GET succeeds with original bucket/key.
4070S sees network traffic or S3 GET while A380 serves the read.
Returned object size and checksum match the baseline.
```

Negative control:

```text
Temporarily block 4070S cold endpoint or stop cold target only after transition.
Read from A380 should fail or stall for the transitioned object.
Restore cold endpoint and read should succeed again.
```

This proves the source metadata depends on remote cold data.

## 12. Space Movement Acceptance Criteria

Pass if:

```text
A380 source physical footprint for the selected object drops materially.
4070S cold target physical footprint increases by approximately the object size plus MinIO overhead.
A380 S3 GET for the original bucket/key still returns HTTP 200.
Returned object checksum matches pre-transition checksum.
4070S traffic/log evidence appears during the A380 read.
No unrelated prefixes were transitioned.
```

Expected source footprint after transition:

```text
small metadata/stub remains on A380
full object data no longer occupies A380 erasure disks
```

Do not rely only on `df` for a single object:

```text
filesystem df changes may be rounded or delayed
use du -sb on the object path and cold target data path for the primary proof
```

## 13. Rollback Plan

If the test fails before transition:

```bash
mc ilm rule rm "a380/${SOURCE_BUCKET}" --id "<rule-id>"
mc ilm tier rm a380 COLD4070-A380
```

If the object already transitioned and must be brought back hot:

```bash
mc ilm restore "a380/${SOURCE_BUCKET}/${SOURCE_KEY}"
```

Then verify:

```bash
mc cat "a380/${SOURCE_BUCKET}/${SOURCE_KEY}" | sha256sum
```

Keep the cold MinIO data untouched until the source object is confirmed healthy.

## 14. Production Questions To Answer After Smoke Test

| Question | Why it matters |
| --- | --- |
| How fast does the scanner transition existing old objects? | Determines how long old disks stay full. |
| What is the per-source bandwidth into cold MinIO? | Determines cold target network and disk sizing. |
| Can many old MinIO servers tier to one cold target without collision? | Requires source/bucket namespace isolation. |
| How slow is first read from cold tier? | User experience and timeout tuning. |
| What happens when cold MinIO is unavailable? | Defines availability risk for historical data. |
| How much metadata remains on old MinIO? | Determines how much space is truly freed. |
| Does lifecycle transition conflict with existing COLD rules on A380? | A380 currently has transition retry logs. |

## 15. Next Execution Step

Recommended next action:

```text
Deploy isolated 4070S cold MinIO on /data/data2 with port 19500.
Find one real A380 video object >= 100MB.
Run the single-object transition test exactly once.
Record before/after du, df, checksum, and tcpdump/trace evidence.
```

Do not expand to many objects until the single-object space movement and read-through behavior are proven.
