# Real Prefix Cold Backup Tiering Results - 2026-06-05

> Branch: `codex/cold-backup-tiering-test`
> Source old MinIO: A380 `172.16.100.132:9000`
> Cold target MinIO: 4070S `172.16.100.217:18610`
> Restore target MinIO: 4070S `172.16.100.217:18620`
> Purpose: transition a real A380 object prefix, verify source disk relief, verify read-back through old MinIO, generate cold mapping rows, and restore into a fresh MinIO.

## 1. Result

Functional result:

```text
PASS
```

The real-prefix test passed:

```text
15 A380 source objects transitioned to the 4070S cold MinIO.
All 15 objects remained readable through the original A380 source MinIO endpoint.
All 15 objects were restored through mapping into a fresh MinIO.
The A380 source object-path footprint dropped from payload scale to metadata/stub scale.
The 4070S cold target grew by the expected logical payload scale.
```

Important caveat:

```text
Two JPG objects had identical size and SHA256.
The bytes are recoverable, but strict one-to-one mapping needs duplicate handling.
```

## 2. Test Boundary

This test used the existing A380 host MinIO and real data under one controlled prefix.

Source:

| Field | Value |
| --- | --- |
| Host | A380 `172.16.100.132` |
| Service | host MinIO on `9000/9090` |
| Bucket | `sucaiwang` |
| Prefix | `sucaiwang/100192/15581/a` |
| Matched objects | `15` |
| Logical source bytes | `317581009` |

Cold target:

| Field | Value |
| --- | --- |
| Host | 4070S `172.16.100.217` |
| Container | `realprefix_newminio1` |
| Endpoint | `http://172.16.100.217:18610` |
| Console | `http://172.16.100.217:18611` |
| Data dir | `/data/data2/minio-real-prefix-tier-test/new` |
| Bucket | `tier-a380-realprefix-sucaiwang` |
| Cold prefix | `a380-9000/sucaiwang/realprefix-20260605/` |

Restore target:

| Field | Value |
| --- | --- |
| Container | `realprefix_restore` |
| Endpoint | `http://172.16.100.217:18620` |
| Console | `http://172.16.100.217:18621` |
| Data dir | `/data/data2/minio-real-prefix-tier-test/restore` |
| Bucket | `restore-sucaiwang` |

The cold target container remains running because the transitioned A380 source objects now depend on this cold endpoint for normal reads.

## 3. Source Space Change

Before transition, object-path footprint on A380:

| Path | Bytes |
| --- | ---: |
| `/data/data1` selected object paths | `158832890` |
| `/data/data2` selected object paths | `158832890` |
| `/data/data3` selected object paths | `158832890` |
| `/data/data4` selected object paths | `158832890` |
| Total | `635331560` |

After transition:

| Path | Bytes |
| --- | ---: |
| `/data/data1` selected object paths | `36228` |
| `/data/data2` selected object paths | `36228` |
| `/data/data3` selected object paths | `36228` |
| `/data/data4` selected object paths | `36228` |
| Total | `144912` |

Source `.minio.sys/tmp/.trash` after transition:

| Path | Bytes |
| --- | ---: |
| `/data/data1/.minio.sys/tmp/.trash` | `27158` |
| `/data/data2/.minio.sys/tmp/.trash` | `27158` |
| `/data/data3/.minio.sys/tmp/.trash` | `27158` |
| `/data/data4/.minio.sys/tmp/.trash` | `27158` |
| Total | `108632` |

Interpretation:

```text
The selected source paths dropped from 635331560 bytes to 144912 bytes.
This confirms payload bytes moved away from the A380 object paths.
The remaining bytes are metadata/stub scale.
```

## 4. Cold Target Growth

Cold target bucket bytes:

| Stage | Bytes |
| --- | ---: |
| Before transition | `8402601` |
| After transition | `326017403` |
| Delta | `317614802` |

The cold target delta matches the source logical payload scale:

```text
source logical bytes: 317581009
cold target delta:    317614802
```

## 5. Lifecycle And Tier Actions

The test added a dedicated remote tier on A380:

| Field | Value |
| --- | --- |
| Tier name | `COLD_4070_REALPREFIX_20260605` |
| Endpoint | `http://172.16.100.217:18610` |
| Bucket | `tier-a380-realprefix-sucaiwang` |
| Prefix | `a380-9000/sucaiwang/realprefix-20260605/` |

Lifecycle rule:

| Field | Value |
| --- | --- |
| Rule id | `d8h6861pqccc73d2qp6g` |
| Source bucket | `sucaiwang` |
| Source prefix | `sucaiwang/100192/15581/a` |
| Transition days | `0` |
| Tier | `COLD_4070_REALPREFIX_20260605` |

Transition completed quickly:

```text
transitioned=15
standard_left=0
cold_keys=15
```

After transition, the test lifecycle rule was removed.

The remote tier configuration remains and must remain while transitioned source objects are expected to read through A380.

## 6. Mapping Result

Cold bucket before/after diff:

| Metric | Value |
| --- | ---: |
| New cold objects | `15` |
| Mapping rows | `15` |
| Missing mappings | `0` |
| Ambiguous rows | `2` |

Ambiguous rows:

```text
sucaiwang/100192/15581/aee51d7b-c753-4282-89dc-8dea5ab35248.jpg
sucaiwang/100192/15581/af91d2ce-ed29-451f-9f34-58c04de71d3e.jpg
```

Both had:

```text
size:   774274
sha256: 3d62ebae86bbdba65c7ee56fc8666208ac36f7f10f151877071a5b80c0ecc21f
```

Interpretation:

```text
Mapping by size + SHA256 can be ambiguous when multiple source keys have identical bytes.
This is acceptable for byte recovery if the payload is truly identical.
It is not enough for strict one-to-one audit or metadata recovery.
Production mapping must explicitly record and handle duplicate-payload groups.
```

## 7. Read-Back And Restore Verification

Final verification log:

```text
/data/data2/minio-real-prefix-tier-test/results-verify-20260605-135646.log
```

Source read-back through A380:

```text
READ_BACK_OK=15
READ_BACK_FAIL=0
```

Restore through mapping into the fresh restore MinIO:

```text
RESTORE_OK=15
RESTORE_FAIL=0
RESTORE_BYTES=317621288
VERIFY_RESULT PASS
```

The restore byte count is slightly larger than source logical bytes because MinIO restore-side accounting includes object metadata overhead in the tested path. Object byte checks passed.

New upload isolation check:

```text
newminio1 normal web bucket object SHA256 stayed unchanged during the cold transition test
```

## 8. Remote Test Artifacts

Artifacts remain on 4070S:

```text
/data/data2/minio-real-prefix-tier-test
/root/minio-real-prefix-tier-test-run.sh
/root/minio-real-prefix-tier-test-continue.sh
/root/minio-real-prefix-tier-test-verify.sh
```

Important files:

```text
/data/data2/minio-real-prefix-tier-test/source-manifest.tsv
/data/data2/minio-real-prefix-tier-test/cold-manifest.tsv
/data/data2/minio-real-prefix-tier-test/mapping.tsv
/data/data2/minio-real-prefix-tier-test/results-20260605-135210.log
/data/data2/minio-real-prefix-tier-test/results-continue-20260605-135426.log
/data/data2/minio-real-prefix-tier-test/results-verify-20260605-135646.log
```

## 9. Interpretation

Confirmed:

```text
Real A380 prefix transition works against a version-aligned 4070S cold MinIO.
Source object paths shrink to metadata/stub scale.
Old source MinIO remains the user-facing read path.
Cold internal objects can be discovered by before/after cold prefix listing.
Mapping-based restore works for this 15-object prefix.
newminio1 can keep a normal upload bucket separate from cold-tier data in the same service.
```

Still required before production:

```text
repeat on production-main MinIO 2022 with real data scale
run 100+ object batches with concurrent uploads and reads
record first-byte latency and full-read latency before/after transition
measure lifecycle worker throughput over hours
define duplicate-payload mapping policy
test metadata and content-type restoration
test versioned buckets if any source has versioning enabled
test capacity alarms and cold target failure behavior
```

## 10. Recommendation

Proceed to a production-like 2022 same-version prefix test:

```text
one old MinIO
one cold MinIO
one source bucket
one bounded prefix
same MinIO release on source and cold target
mapping generated during transition
restore drill before expanding
```

Do not run a broad full-bucket lifecycle transition until:

```text
the mapping worker is deterministic
duplicate payload handling is accepted
restore drills pass for sampled batches
the cold target has enough capacity and monitoring
```
