# VideoId Cold Backup Smoke Results - 2026-06-05

> Branch: `codex/cold-backup-tiering-test`
> Corrected input row: `/Users/zhangyang/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_h31nspprs8pn12_318a/msg/file/2026-06/14708948.json`
> Source: A380 original MinIO `172.16.100.132:9000`
> Cold target: 4070S test MinIO `172.16.100.217:18610`
> Restore target: 4070S restore MinIO `172.16.100.217:18620`
> Business id: `video.id = 14708948`

## 1. Result

```text
PASS
```

The corrected `video` row supports the expected five-file business migration unit.

The smoke completed all required checks:

```text
5/5 source objects found on A380
5/5 objects transitioned through MinIO lifecycle to 4070S cold MinIO
5/5 source objects changed from STANDARD to COLD_4070_VIDEOID5_14708948_20260605
A380 source physical footprint dropped from 312304728 bytes to 14124 bytes
4070S cold bucket footprint increased by 156145437 bytes
5/5 cold objects mapped by size + SHA256
5/5 objects restored into restore MinIO under original bucket/key
5/5 source, cold, and restore HTTP HEAD checks returned 200
```

Important operational timing:

```text
Lifecycle rule creation was not enough.
The A380 scanner took about 756 seconds before the five objects transitioned.
Production runs must wait for actual storage-class changes and source footprint shrink before declaring space freed.
```

## 2. Business Object Group

Corrected row fields:

| DB field | Value |
| --- | --- |
| `cover_url` | `address/sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8.jpg` |
| `video_raw_url` | `address/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_h265.MOV` |
| `video_url` | `address/sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8.mp4` |

Resolved A380 object manifest:

| Role | Source bucket | Source key | Size |
| --- | --- | --- | ---: |
| `source_upload` | `sucaiwang` | `sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae.MOV` | `107204861` |
| `cover` | `sucaiwang` | `sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8.jpg` | `290080` |
| `watermark_source` | `sucaiwang` | `sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_mark919.MOV` | `38044089` |
| `transcoded_video` | `sucaiwang` | `sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_h265.MOV` | `7167813` |
| `playback_video` | `sucaiwang` | `sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8.mp4` | `3431347` |

Total logical bytes:

```text
156138190
```

The source path transform for this row is:

```text
address/sucaiwang/100192/15624/<file>
  -> bucket=sucaiwang
  -> key=sucaiwang/100192/15624/<file>
```

## 3. Lifecycle Transition

Cold tier configuration used for the test:

```text
tier name: COLD_4070_VIDEOID5_14708948_20260605
cold bucket: tier-a380-videoid5-sucaiwang
cold prefix: a380-9000/sucaiwang/videoid-14708948-fivefile-20260605/
```

Lifecycle rules were intentionally narrow:

```text
prefix: sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8
prefix: sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae
```

Rules used and removed after transition:

```text
d8h92hppqccc738k8hig
d8h92hppqccc73aaglmg
```

Final lifecycle cleanup check:

```text
FINAL_RULES_FOUND 0
```

Observed transition:

```text
WAIT elapsed=756s transitioned=5/5 standard=0 other=0
```

Final source storage class:

| Role | Storage class |
| --- | --- |
| `source_upload` | `COLD_4070_VIDEOID5_14708948_20260605` |
| `cover` | `COLD_4070_VIDEOID5_14708948_20260605` |
| `watermark_source` | `COLD_4070_VIDEOID5_14708948_20260605` |
| `transcoded_video` | `COLD_4070_VIDEOID5_14708948_20260605` |
| `playback_video` | `COLD_4070_VIDEOID5_14708948_20260605` |

## 4. Space Movement

A380 source physical footprint:

| Phase | Bytes |
| --- | ---: |
| before transition | `312304728` |
| after transition | `14124` |
| freed | `312290604` |

4070S cold bucket footprint:

| Phase | Bytes |
| --- | ---: |
| before transition | `0` |
| after transition | `156145437` |
| delta | `156145437` |

This proves the expected MinIO tiering behavior for this videoId group:

```text
A380 keeps small metadata/stub entries.
Payload bytes moved to the 4070S cold MinIO bucket.
Original A380 source URLs continue to serve the objects.
```

## 5. Mapping And Restore

Mapping evidence on 4070S:

```text
/data/data2/minio-videoid-14708948-fivefile-tier-test/mapping.tsv
/data/data2/minio-videoid-14708948-fivefile-tier-test/restore-verify-fixed.tsv
```

Mapping result:

```text
COLD_NEW_OBJECT_COUNT 5
MAPPING_MATCHED_COUNT 5/5
RESTORE_OK_FIXED 5/5
```

Cold internal keys:

| Role | Cold key |
| --- | --- |
| `source_upload` | `a380-9000/sucaiwang/videoid-14708948-fivefile-20260605/709faf2a18b99804/b9/eb/b9eb7b46-1748-4ccb-b04f-1cd657fa05c4` |
| `cover` | `a380-9000/sucaiwang/videoid-14708948-fivefile-20260605/709faf2a18b99804/55/d4/55d40806-99c5-4810-b1f5-31626cfa8434` |
| `watermark_source` | `a380-9000/sucaiwang/videoid-14708948-fivefile-20260605/709faf2a18b99804/7f/15/7f15c1e7-3b96-4784-bca7-e352cdcd5071` |
| `transcoded_video` | `a380-9000/sucaiwang/videoid-14708948-fivefile-20260605/709faf2a18b99804/4d/c9/4dc903f7-1223-4834-8819-058bded3efe0` |
| `playback_video` | `a380-9000/sucaiwang/videoid-14708948-fivefile-20260605/709faf2a18b99804/9c/82/9c82541e-270a-4ebd-901c-b265ab9fe7eb` |

## 6. Verified Access URLs

The two 4070S test buckets were set to anonymous download for this smoke only. Production access policy must be decided separately.

All source, cold, and restore HEAD checks returned HTTP `200`.

| Role | Source URL | Cold URL | Restore URL |
| --- | --- | --- | --- |
| `source_upload` | `http://172.16.100.132:9000/sucaiwang/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae.MOV` | `http://172.16.100.217:18610/tier-a380-videoid5-sucaiwang/a380-9000/sucaiwang/videoid-14708948-fivefile-20260605/709faf2a18b99804/b9/eb/b9eb7b46-1748-4ccb-b04f-1cd657fa05c4` | `http://172.16.100.217:18620/restore-sucaiwang/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae.MOV` |
| `cover` | `http://172.16.100.132:9000/sucaiwang/sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8.jpg` | `http://172.16.100.217:18610/tier-a380-videoid5-sucaiwang/a380-9000/sucaiwang/videoid-14708948-fivefile-20260605/709faf2a18b99804/55/d4/55d40806-99c5-4810-b1f5-31626cfa8434` | `http://172.16.100.217:18620/restore-sucaiwang/sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8.jpg` |
| `watermark_source` | `http://172.16.100.132:9000/sucaiwang/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_mark919.MOV` | `http://172.16.100.217:18610/tier-a380-videoid5-sucaiwang/a380-9000/sucaiwang/videoid-14708948-fivefile-20260605/709faf2a18b99804/7f/15/7f15c1e7-3b96-4784-bca7-e352cdcd5071` | `http://172.16.100.217:18620/restore-sucaiwang/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_mark919.MOV` |
| `transcoded_video` | `http://172.16.100.132:9000/sucaiwang/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_h265.MOV` | `http://172.16.100.217:18610/tier-a380-videoid5-sucaiwang/a380-9000/sucaiwang/videoid-14708948-fivefile-20260605/709faf2a18b99804/4d/c9/4dc903f7-1223-4834-8819-058bded3efe0` | `http://172.16.100.217:18620/restore-sucaiwang/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_h265.MOV` |
| `playback_video` | `http://172.16.100.132:9000/sucaiwang/sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8.mp4` | `http://172.16.100.217:18610/tier-a380-videoid5-sucaiwang/a380-9000/sucaiwang/videoid-14708948-fivefile-20260605/709faf2a18b99804/9c/82/9c82541e-270a-4ebd-901c-b265ab9fe7eb` | `http://172.16.100.217:18620/restore-sucaiwang/sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8.mp4` |

## 7. Implications

This corrected smoke now validates the intended complete workflow:

```text
videoId -> five-file manifest -> lifecycle transition -> A380 source-space release -> cold mapping -> restore drill
```

The main production risk is not object resolution for this row. The main operational risk is lifecycle scanner timing:

```text
Do not assume transition happens immediately after rule creation.
Monitor object storage class and source physical footprint.
Keep lifecycle rules narrow and remove them after the batch.
Record mapping during the batch before expanding migration scope.
```
