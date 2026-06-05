# MinIO Hybrid Role + Mapping Recovery Results - 2026-06-05

> Branch: `codex/cold-backup-tiering-test`
> Test host: 4070S `172.16.100.217`
> Purpose: verify whether one `newminio1` can both serve new business uploads and receive `oldminio1` cold-tier transitioned objects, then recover a transitioned object using a DB-style mapping after `oldminio1` is unavailable.

## 1. Result

Functional result:

```text
PASS
```

The proposed mixed-role layout worked in an isolated same-version test:

```text
oldminio1 -> newminio1 cold-tier bucket
new web uploads -> newminio1 normal web bucket
mapping table -> cold internal key -> restore into fresh MinIO
```

Important conclusion:

```text
newminio1 can carry both roles if bucket, credentials, quota, and monitoring are isolated.
The cold-tier URL/key is not a business URL. It should be recorded only in a recovery mapping table.
```

## 2. Test Boundary

This was an isolated Docker test using fresh empty data directories:

```text
/data/data2/minio-hybrid-role-test
```

It did not touch:

```text
A380 original MinIO data
4070S current systemd MinIO on 9000/9090
existing production-style 64T data directories
```

Temporary containers were removed after the test. Logs and small test data remain on 4070S:

```text
/data/data2/minio-hybrid-role-test/results-20260605-125714.log
/root/minio-hybrid-role-test-run.sh
```

## 3. Topology

All MinIO services used the same production-main version:

```text
RELEASE.2022-11-08T05-27-07Z
```

| Role | Endpoint | Data dir | Purpose |
| --- | --- | --- | --- |
| `oldminio1` | `http://172.16.100.217:18500` | `/data/data2/minio-hybrid-role-test/old` | simulate old source MinIO |
| `newminio1` | `http://172.16.100.217:18510` | `/data/data2/minio-hybrid-role-test/new` | cold-tier receiver and new upload MinIO |
| `restore` | `http://172.16.100.217:18520` | `/data/data2/minio-hybrid-role-test/restore` | fresh MinIO restore target |

`newminio1` used separated buckets:

| Bucket | Role |
| --- | --- |
| `tier-oldminio1-sucaiwang` | `oldminio1` cold-tier target, internal/recovery only |
| `web-upload-sucaiwang` | normal new web uploads |

## 4. Test Objects

| Object | Bucket/key | Size | SHA256 |
| --- | --- | ---: | --- |
| old object | `old-sucaiwang/legacy-user-1001/video-0001.bin` | `33554432` | `48aec35365578a10071038f5f895b049f7a2cf8b8c0ce0d98e2b9e3d8bf9b1da` |
| new web object | `web-upload-sucaiwang/web-user-2001/new-upload-before.bin` | `16777216` | `ed8aaf813aa55c24fa88089d307e218bfffe456d013e78fa4f335c9f78b17a80` |

## 5. Hybrid Role Evidence

`oldminio1` configured a remote tier pointing to `newminio1`:

```text
Name: COLD_OLDMINIO1
Endpoint: http://172.16.100.217:18510
Bucket: tier-oldminio1-sucaiwang
Prefix: oldminio1/sucaiwang/
```

Lifecycle rule:

```text
Prefix: legacy-user-1001/video-0001.bin
Days to tier: 0
Tier: COLD_OLDMINIO1
```

At the same time, `newminio1` accepted normal web uploads into `web-upload-sucaiwang`.

Concurrent web upload checks:

```text
WEB_UPLOAD_DONE 1 ed8aaf813aa55c24fa88089d307e218bfffe456d013e78fa4f335c9f78b17a80
WEB_UPLOAD_DONE 2 ed8aaf813aa55c24fa88089d307e218bfffe456d013e78fa4f335c9f78b17a80
WEB_UPLOAD_DONE 3 ed8aaf813aa55c24fa88089d307e218bfffe456d013e78fa4f335c9f78b17a80
WEB_UPLOAD_DONE 4 ed8aaf813aa55c24fa88089d307e218bfffe456d013e78fa4f335c9f78b17a80
WEB_UPLOAD_DONE 5 ed8aaf813aa55c24fa88089d307e218bfffe456d013e78fa4f335c9f78b17a80
WEB_UPLOAD_DONE 6 ed8aaf813aa55c24fa88089d307e218bfffe456d013e78fa4f335c9f78b17a80
WEB_UPLOAD_DONE 7 ed8aaf813aa55c24fa88089d307e218bfffe456d013e78fa4f335c9f78b17a80
WEB_UPLOAD_DONE 8 ed8aaf813aa55c24fa88089d307e218bfffe456d013e78fa4f335c9f78b17a80
```

Transition evidence:

```text
X-Amz-Storage-Class: COLD_OLDMINIO1
old_object_bytes: 33555871 -> 687
newminio1 bytes: 151019009 -> 184818511
```

Read checks after transition:

```text
old_after=48aec35365578a10071038f5f895b049f7a2cf8b8c0ce0d98e2b9e3d8bf9b1da
web_after=ed8aaf813aa55c24fa88089d307e218bfffe456d013e78fa4f335c9f78b17a80
web_concurrent=ed8aaf813aa55c24fa88089d307e218bfffe456d013e78fa4f335c9f78b17a80
```

## 6. Mapping Recovery Evidence

After transition, the cold-tier bucket produced exactly one new cold object key:

```text
oldminio1/sucaiwang/32d60a29-3a1c-46bb-978e-4f4f6d4958e6/old-sucaiwang/73/e9/73e94634-7fa5-4447-b5d8-6ec2c7130773
```

The object was readable through the `newminio1` S3 API and matched the old object:

```text
candidate rc=0
candidate size=32 MiB
candidate sha=48aec35365578a10071038f5f895b049f7a2cf8b8c0ce0d98e2b9e3d8bf9b1da
mapping match_count=1
```

Mapping row captured by the test:

```text
source_id: oldminio1
source_bucket: old-sucaiwang
source_key: legacy-user-1001/video-0001.bin
cold_bucket: tier-oldminio1-sucaiwang
cold_object_key: oldminio1/sucaiwang/32d60a29-3a1c-46bb-978e-4f4f6d4958e6/old-sucaiwang/73/e9/73e94634-7fa5-4447-b5d8-6ec2c7130773
sha256: 48aec35365578a10071038f5f895b049f7a2cf8b8c0ce0d98e2b9e3d8bf9b1da
```

Then the test stopped `oldminio1`:

```text
hybrid_oldminio1 Exited
```

Using only `newminio1` plus the mapping row, the object was read from the cold-tier key and restored to a fresh MinIO under the original bucket/key:

```text
new/tier-oldminio1-sucaiwang/<cold_object_key>
  -> restore/old-sucaiwang/legacy-user-1001/video-0001.bin
```

Restore verification:

```text
COLD_SHA=48aec35365578a10071038f5f895b049f7a2cf8b8c0ce0d98e2b9e3d8bf9b1da
COLD_BYTES=33554432
RESTORE_SHA=48aec35365578a10071038f5f895b049f7a2cf8b8c0ce0d98e2b9e3d8bf9b1da
VERIFY_RESULT PASS
```

## 7. Space Snapshot

Final space snapshot:

| Path | Bytes |
| --- | ---: |
| `/data/data2/minio-hybrid-role-test/old` | `33814123` |
| `/data/data2/minio-hybrid-role-test/new` | `184939084` |
| `/data/data2/minio-hybrid-role-test/restore` | `33932944` |
| old source object path | `687` |
| old source `.minio.sys/tmp/.trash` | `33559552` |

The source object path reduced to metadata scale, but the old payload still existed temporarily in `.minio.sys/tmp/.trash`. This matches the earlier version compatibility result and should be monitored in production.

## 8. Interpretation

Confirmed:

```text
newminio1 can simultaneously receive oldminio1 cold-tier transitioned objects and normal new web uploads.
Separate buckets are enough for a functional smoke test.
The cold-tier internal key can be discovered by before/after cold bucket listing in this one-object test.
That internal cold object can be read through newminio1 S3 API.
Mapping-based restore into a fresh MinIO works for this one object after oldminio1 is stopped.
```

Still not proven:

```text
large-scale concurrent migration and web uploads stay within latency/error budgets
mapping discovery remains unambiguous for many objects transitioning concurrently
restore preserves all object metadata and versioning behavior
trash cleanup timing is acceptable under production load
newminio1 capacity and IO remain healthy with both roles active
```

## 9. Recommendation

Proceed to the next validation stage with the same-version `RELEASE.2022-11-08T05-27-07Z` plan:

```text
1. Keep newminio1 as a single service with isolated buckets.
2. Use a dedicated bucket for oldminio1 cold-tier data.
3. Use separate buckets for normal new web uploads.
4. Record cold-tier internal keys only in a recovery mapping table.
5. Do not store cold-tier internal URLs in the existing business DB.
6. Run a 10-100 object prefix test before any production wave.
```

For the prefix test, avoid many objects transitioning at the exact same time until mapping discovery has a deterministic reconciliation strategy.

