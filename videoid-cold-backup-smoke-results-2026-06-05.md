# VideoId Cold Backup Smoke Results - 2026-06-05

> Branch: `codex/cold-backup-tiering-test`
> Source: A380 original MinIO `172.16.100.132:9000`
> Cold target: 4070S test MinIO `172.16.100.217:18610`
> Restore target: 4070S restore MinIO `172.16.100.217:18620`
> Business id: `video.id = 14708948`

## 1. Result

```text
PASS for videoId-based object resolution, cold copy, mapping, and restore verification.
NOT COMPLETE for lifecycle-driven source space release on this specific videoId sample.
```

This smoke proves that a `videoId` can drive a small migration manifest and that the resolved objects can be copied to cold MinIO and restored under the original bucket/key.

It does not prove that the same `videoId` objects immediately free A380 disk space through MinIO lifecycle transition. The lifecycle rule was valid and the remote tier was reachable, but the A380 scanner did not reach the target object directory during the observation window.

## 2. Business Object Group

The test used the clarified `video_raw_url` derivation rule.

| Role | Source bucket | Source key | Size |
| --- | --- | --- | ---: |
| `source_upload` | `sucaiwang` | `sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae.MOV` | `107204861` |
| `watermark_source` | `sucaiwang` | `sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_mark919.MOV` | `38044089` |
| `transcoded_video` | `sucaiwang` | `sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_h265.MOV` | `7167813` |

Total logical bytes:

```text
152416763
```

The exact source prefix check returned exactly these 3 objects:

```text
sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae
```

## 3. Lifecycle Transition Attempt

Test tier:

```text
tier name: COLD_4070_VIDEOID_14708948_20260605
cold bucket: tier-a380-videoid-sucaiwang
cold prefix: a380-9000/sucaiwang/videoid-14708948-20260605/
```

Observed facts:

```text
remote tier connectivity check passed
lifecycle rule prefix matched exactly the 3-object stem
lifecycle rule exported with Status=Enabled and Days=0
objects stayed STANDARD during the wait
cold bucket did not receive lifecycle-created objects
scanner trace sampled 637 events but did not reach the target cf98a722... object directory
temporary lifecycle rules were removed after the test
```

Rule ids used and removed:

```text
d8h88o9pqccc73c6kg5g
d8h8du1pqccc73dblik0
```

Interpretation:

```text
MinIO lifecycle transition is scanner-driven and not synchronous.
For this particular sample, the scanner did not process the target path during the test window.
This is an operational timing risk, not proof that the tier configuration is invalid.
Production waves must monitor actual storage-class changes and cold-prefix deltas instead of assuming immediate transition after rule creation.
```

## 4. Cold Copy And Restore Smoke

Because the lifecycle scanner did not process the target prefix during the test window, a safe copy-based smoke was run without deleting A380 source objects.

Cold copy prefix:

```text
tier-a380-videoid-sucaiwang/a380-9000/sucaiwang/videoid-14708948-manual-copy-20260605/
```

Restore bucket:

```text
restore-sucaiwang
```

Server-side result:

```text
SOURCE_LOGICAL_BYTES 152416763
COLD_BUCKET_DU_BEFORE_BYTES 0
COLD_BUCKET_DU_AFTER_BYTES 152422815
COLD_BUCKET_DU_DELTA_BYTES 152422815
COPY_RESTORE_OK_COUNT 3/3
VERIFY_RESULT PASS
```

Evidence file on 4070S:

```text
/data/data2/minio-videoid-14708948-tier-test/videoid-14708948-copy-smoke.tsv
```

## 5. Verified Access URLs

The two test buckets were set to anonymous download for this smoke only. Production access policy must be decided separately.

Cold-copy URLs:

| Role | HTTP | Size | URL |
| --- | --- | ---: | --- |
| `source_upload` | `200` | `107204861` | `http://172.16.100.217:18610/tier-a380-videoid-sucaiwang/a380-9000/sucaiwang/videoid-14708948-manual-copy-20260605/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae.MOV` |
| `watermark_source` | `200` | `38044089` | `http://172.16.100.217:18610/tier-a380-videoid-sucaiwang/a380-9000/sucaiwang/videoid-14708948-manual-copy-20260605/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_mark919.MOV` |
| `transcoded_video` | `200` | `7167813` | `http://172.16.100.217:18610/tier-a380-videoid-sucaiwang/a380-9000/sucaiwang/videoid-14708948-manual-copy-20260605/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_h265.MOV` |

Restore URLs:

| Role | HTTP | Size | URL |
| --- | --- | ---: | --- |
| `source_upload` | `200` | `107204861` | `http://172.16.100.217:18620/restore-sucaiwang/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae.MOV` |
| `watermark_source` | `200` | `38044089` | `http://172.16.100.217:18620/restore-sucaiwang/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_mark919.MOV` |
| `transcoded_video` | `200` | `7167813` | `http://172.16.100.217:18620/restore-sucaiwang/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_h265.MOV` |

## 6. Implications

What this validates:

```text
videoId -> object manifest can drive migration work.
The 3 derived video payload roles can be copied to cold MinIO.
The copied objects can be restored to the original bucket/key on another MinIO.
The mapping file can be generated during migration and used for restore verification.
```

What remains open:

```text
The full five-role group still needs live DB confirmation for cover and playback_video.
Lifecycle transition for this exact videoId sample did not complete during the scanner observation window.
Source A380 disk space was not freed in this copy smoke because the source objects were intentionally not deleted.
Production capacity relief still depends on lifecycle transition completion or a deliberate delete-after-archive design.
```
