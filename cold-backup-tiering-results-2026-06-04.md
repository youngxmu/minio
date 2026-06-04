# Cold Backup MinIO Tiering Results - 2026-06-04

> Branch: `codex/cold-backup-tiering-test`
> Run id: `cold-tier-smoke-20260604-dba000ae`
> Source old MinIO: A380 `172.16.100.132:9000`
> Cold backup MinIO: 4070S `172.16.100.217:9000`

## 1. Result

Functional result:

```text
PASS
```

The single-object cold-backup tiering flow worked:

```text
1. A380 kept the original bucket/key access path.
2. The selected object's source-side physical footprint shrank to metadata/stub scale.
3. 4070S received the transitioned object payload.
4. Reading the object from A380 still returned the original bytes.
5. Packet capture showed A380 fetching data from 4070S during the read.
```

This validates the technical direction for freeing old MinIO data disks by using MinIO lifecycle transition to a remote cold MinIO. It does not validate source MinIO disaster recovery.

## 2. Tested Object

| Field | Value |
| --- | --- |
| Bucket | `sucaiwang` |
| Key | `sucaiwang/200001/5/dba000ae-bc3f-4f1a-a600-7c4aec1c57a5.mp4` |
| Original access path | `http://172.16.100.132:9000/sucaiwang/sucaiwang/200001/5/dba000ae-bc3f-4f1a-a600-7c4aec1c57a5.mp4` |
| Logical size | `458997386` bytes |
| ETag | `"a4e61191aca88ba7a89d7127f150286a-88"` |
| SHA256 before transition | `81aab9984e5d4c94137c93afaa008bac35cffbebd9a5b9df1e2f2b55f12fed7b` |
| SHA256 after transition | `81aab9984e5d4c94137c93afaa008bac35cffbebd9a5b9df1e2f2b55f12fed7b` |

## 3. Source Space Change On A380

Before transition, the selected object occupied about 229 MB on each of the four A380 erasure disks:

| Path | Bytes |
| --- | ---: |
| `/data/data1/.../dba000ae-bc3f-4f1a-a600-7c4aec1c57a5.mp4` | `229514081` |
| `/data/data2/.../dba000ae-bc3f-4f1a-a600-7c4aec1c57a5.mp4` | `229514081` |
| `/data/data3/.../dba000ae-bc3f-4f1a-a600-7c4aec1c57a5.mp4` | `229514081` |
| `/data/data4/.../dba000ae-bc3f-4f1a-a600-7c4aec1c57a5.mp4` | `229514081` |
| Total | `918056324` |

After transition, only small source-side metadata/stub directories remained:

| Path | Bytes |
| --- | ---: |
| `/data/data1/.../dba000ae-bc3f-4f1a-a600-7c4aec1c57a5.mp4` | `1602` |
| `/data/data2/.../dba000ae-bc3f-4f1a-a600-7c4aec1c57a5.mp4` | `1602` |
| `/data/data3/.../dba000ae-bc3f-4f1a-a600-7c4aec1c57a5.mp4` | `1602` |
| `/data/data4/.../dba000ae-bc3f-4f1a-a600-7c4aec1c57a5.mp4` | `1602` |
| Total | `6408` |

Source-side freed physical footprint for this object:

```text
918056324 - 6408 = 918049916 bytes
```

## 4. Cold Target Evidence On 4070S

The cold target bucket path is the existing 4070S MinIO data path:

```text
/data/data2/data/sucaiwang
```

After transition, recent large files appeared under a MinIO tiering hash prefix:

| File | Bytes |
| --- | ---: |
| `.../709faf2a18b99804/6c/ee/.../part.1` | `134221824` |
| `.../709faf2a18b99804/6c/ee/.../part.2` | `134221824` |
| `.../709faf2a18b99804/6c/ee/.../part.3` | `134221824` |
| `.../709faf2a18b99804/6c/ee/.../part.4` | `56345930` |

The four large part files total about 459 MB, matching the logical object size scale.

Current 4070S space snapshot:

| Path | Bytes |
| --- | ---: |
| `/data/data2/data/sucaiwang` | `30559835991` |
| `/data/data2/data/.minio.sys` | `141698831` |
| `/data/data2/cold-backup-minio-test/data` | `2048076` |

The target bucket already had background lifecycle activity from an older broad rule, so the bucket-level delta is not used as the sole proof for this object. The object-level proof is the source footprint shrink, the newly written cold target part files, and the read-back checksum.

## 5. Read-Back And Data Flow

Read-back through the original A380 endpoint:

```text
GET_STATUS 200
CONTENT_LENGTH 458997386
STORAGE_CLASS COLD
GET_BYTES 458997386
SHA256 81aab9984e5d4c94137c93afaa008bac35cffbebd9a5b9df1e2f2b55f12fed7b
```

Packet capture on 4070S during the A380 read:

```text
20 packets captured
83 packets received by filter
0 packets dropped by kernel
```

The capture showed traffic between:

```text
172.16.100.132 -> 172.16.100.217:9000
172.16.100.217:9000 -> 172.16.100.132
```

This confirms the user-facing read stayed on the old MinIO path while A380 fetched the transitioned payload from the cold MinIO.

## 6. Lifecycle And Tier Configuration

A380 already had an existing remote tier:

| Field | Value |
| --- | --- |
| Tier name | `COLD` |
| Tier type | `minio` |
| Endpoint | `http://172.16.100.217:9000` |
| Target bucket | `sucaiwang` |

The test used a narrow lifecycle rule for exactly one object:

| Rule | Status | Scope |
| --- | --- | --- |
| `cold-tier-smoke-20260604-dba000ae` | `Enabled` | exact selected key prefix |
| `d6rrrnico5mpa7f4i910` | `Disabled` | old broad 45-day full-bucket rule |

Current lifecycle shape:

```xml
<LifecycleConfiguration>
  <Rule>
    <ID>d6rrrnico5mpa7f4i910</ID>
    <Status>Disabled</Status>
    <Filter><Prefix /></Filter>
    <Transition><Days>45</Days><StorageClass>COLD</StorageClass></Transition>
  </Rule>
  <Rule>
    <ID>cold-tier-smoke-20260604-dba000ae</ID>
    <Status>Enabled</Status>
    <Filter>
      <Prefix>sucaiwang/200001/5/dba000ae-bc3f-4f1a-a600-7c4aec1c57a5.mp4</Prefix>
    </Filter>
    <Transition><StorageClass>COLD</StorageClass></Transition>
  </Rule>
</LifecycleConfiguration>
```

## 7. Important Runtime Change On 4070S

The original 4070S Docker MinIO on `9000/9090` was an older MinIO build. A380 logs showed remote transition failures with `Bad sha256`, and the old target version was the likely cause.

To complete the smoke test, 4070S was changed as follows:

```text
1. Backed up the old Docker MinIO metadata and environment to:
   /data/data2/cold-backup-minio-test/recovery-20260604-134821
2. Copied the A380 MinIO 2025 binary to 4070S:
   /usr/local/bin/minio-2025-a380
3. Stopped Docker container:
   minio_local
4. Started systemd service:
   minio-cold-local.service
5. Confirmed health:
   http://127.0.0.1:9000/minio/health/ready -> 200
```

Current state:

| Service | State |
| --- | --- |
| `minio-cold-local.service` | active |
| `minio_local` Docker container | stopped |
| `minio_cold_backup_test` on `19500/19590` | removed after cleanup because it was not used |

Do not restore the old Docker MinIO on `9000/9090` without retesting, because that may reintroduce the transition checksum failure.

## 8. Production Implications

Confirmed:

```text
MinIO tiering can move object payload data off old independent MinIO disks while keeping reads through the old host/bucket/key.
```

Still required before production:

```text
1. Align MinIO versions between all old sources and the cold target.
2. Use isolated cold buckets or namespaces per source MinIO to avoid bucket/key collisions.
3. Keep old source MinIO metadata protected; cold tier data alone is not a full backup.
4. Add lifecycle rules in batches by exact prefix or controlled age windows, not by broad full-bucket rules at first.
5. Rate-limit transition workers so cold migration does not compete with active uploads or reads.
6. Measure directory count/inode pressure after large-scale transition; source-side metadata remains and may not solve every directory-scaling issue.
7. Build an operational rollback plan before re-enabling any broad lifecycle rule.
```

## 9. Next Test Recommendation

Next run should migrate a small controlled prefix, for example 10 to 100 videos from one user prefix, and record:

```text
source disk freed bytes
cold target written bytes
transition duration
read latency before and after transition
concurrent upload/read impact
MinIO lifecycle worker logs
directory count and inode count before/after
```

