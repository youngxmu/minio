# Cold Backup Delete Smoke Results - 2026-06-08

> Branch: `codex/cold-backup-tiering-test`
> Run id: `delete-smoke-20260608-134624`
> Source old MinIO: A380 `172.16.100.132:9000`
> Cold target MinIO: 4070S `172.16.100.217:9000`

## 1. Result

```text
PASS
```

This smoke used two newly-created random 8 MiB test objects, not business video data:

```text
verify.bin  -> transitioned and retained for manual access verification
delete.bin  -> transitioned, then deleted through the A380 source MinIO
```

Observed behavior:

```text
Both objects transitioned from A380 to the 4070S cold tier.
The batch lifecycle rule was removed after transition.
delete.bin was deleted through the source A380 bucket/key.
The source URL for delete.bin returned 404.
The cold internal URL for delete.bin returned 404.
verify.bin remained readable through both the A380 source URL and the 4070S cold URL.
```

## 2. Objects

| Role | Source bucket | Source key | Size | SHA256 |
| --- | --- | --- | ---: | --- |
| retained verify object | `sucaiwang` | `sucaiwang/codex-delete-smoke/20260608/delete-smoke-20260608-134624/verify.bin` | `8388608` | `24fdf0c473bafc7d3d225ef60dccfc99aa15d39acd9dc317bad9e456b8db819c` |
| deleted object | `sucaiwang` | `sucaiwang/codex-delete-smoke/20260608/delete-smoke-20260608-134624/delete.bin` | `8388608` | `5600da9fbf50713dcdf48edce39cdd61f23988e8b06f819176239b062e8dd95a` |

## 3. Tiering Setup

```text
tier name: COLD_4070_DELETE_SMOKE_20260608_134624
cold bucket: tier-a380-delete-smoke-20260608
cold prefix: a380-9000/sucaiwang/delete-smoke-20260608/delete-smoke-20260608-134624/
rule id: d8j5ej9pqccc73bskgjg
```

Lifecycle result:

```text
WAIT elapsed=60s
verify storage class: COLD_4070_DELETE_SMOKE_20260608_134624
delete storage class: COLD_4070_DELETE_SMOKE_20260608_134624
rule cleanup: RULE_REMOVED=d8j5ej9pqccc73bskgjg
```

Mapping evidence on 4070S:

```text
/root/delete-smoke-20260608-134624/evidence/mapping.tsv
```

Mapped cold internal keys:

| Role | Cold key |
| --- | --- |
| retained verify object | `a380-9000/sucaiwang/delete-smoke-20260608/delete-smoke-20260608-134624/709faf2a18b99804/a6/04/a6048a27-c245-4c8c-a7a6-b08bef2cedba` |
| deleted object | `a380-9000/sucaiwang/delete-smoke-20260608/delete-smoke-20260608-134624/709faf2a18b99804/bd/65/bd65b8d1-27bd-4674-8b34-75258a17e612` |

## 4. Access URLs

The cold test bucket was set to anonymous download so the retained test object can be manually verified. Production cold-tier buckets must not be exposed this way.

Retained object, expected to remain accessible:

| Endpoint | URL | Final code |
| --- | --- | --- |
| A380 source | `http://172.16.100.132:9000/sucaiwang/sucaiwang/codex-delete-smoke/20260608/delete-smoke-20260608-134624/verify.bin` | `206` |
| 4070S cold | `http://172.16.100.217:9000/tier-a380-delete-smoke-20260608/a380-9000/sucaiwang/delete-smoke-20260608/delete-smoke-20260608-134624/709faf2a18b99804/a6/04/a6048a27-c245-4c8c-a7a6-b08bef2cedba` | `206` |

Deleted object, expected to be gone:

| Endpoint | URL | Final code |
| --- | --- | --- |
| A380 source | `http://172.16.100.132:9000/sucaiwang/sucaiwang/codex-delete-smoke/20260608/delete-smoke-20260608-134624/delete.bin` | `404` |
| 4070S cold | `http://172.16.100.217:9000/tier-a380-delete-smoke-20260608/a380-9000/sucaiwang/delete-smoke-20260608/delete-smoke-20260608-134624/709faf2a18b99804/bd/65/bd65b8d1-27bd-4674-8b34-75258a17e612` | `404` |

## 5. Delete Evidence

Before delete:

```text
VERIFY_SOURCE_TRANSITIONED_CODE=206
VERIFY_COLD_TRANSITIONED_CODE=206
DELETE_SOURCE_TRANSITIONED_CODE=206
DELETE_COLD_TRANSITIONED_CODE=206
```

After deleting `delete.bin` through the source A380 bucket/key:

```text
SOURCE_DELETE_ISSUED=OK
DELETE_WAIT elapsed=1s source=404 cold=404
DELETE_SOURCE_FINAL_CODE=404
DELETE_COLD_FINAL_CODE=404
VERIFY_SOURCE_FINAL_CODE=206
VERIFY_COLD_FINAL_CODE=206
DELETE_SMOKE=PASS
```

Independent local curl check:

```text
VERIFY_SOURCE 206
VERIFY_COLD 206
DELETE_SOURCE 404
DELETE_COLD 404
```

## 6. Production Implications

Confirmed for this test shape:

```text
If an already-transitioned object is deleted through the source old MinIO bucket/key,
the source object disappears and the corresponding cold internal object is also deleted.
```

Operational rule:

```text
Business deletes must go through the source old MinIO path while source metadata still owns the transitioned object.
Do not directly delete cold-tier internal objects from the cold MinIO bucket.
Do not add independent lifecycle cleanup rules to cold-tier buckets.
If cold capacity is too high, release data by deleting expired business objects through the source MinIO, then verify source and cold 404.
```

Limitations:

```text
This was a non-business random-object smoke.
This does not cover bucket versioning, object lock, legal hold, or lifecycle expiration semantics.
Production MinIO 2022 delete behavior should be re-smoked with the exact production version and bucket settings before broad rollout.
```

Cleanup note:

```text
verify.bin is intentionally retained so the access URLs above remain testable.
After manual validation, delete verify.bin through the A380 source URL/key, then remove the unique test tier if no objects still reference it.
The temporary copied mc credential configs on 4070S were removed after the smoke.
```
