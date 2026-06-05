# VideoId Business Row Smoke Results - 2026-06-05

> Branch: `codex/cold-backup-tiering-test`
> Superseded input row file: `/Users/zhangyang/Downloads/video.json`
> Corrected input row file: `/Users/zhangyang/Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files/wxid_h31nspprs8pn12_318a/msg/file/2026-06/14708948.json`
> Business id: `video.id = 14708948`
> Expected source: A380 original MinIO

## 1. Result

```text
PASS
```

The earlier JSON row was incorrect and is superseded. Using the corrected JSON row, `videoId=14708948` resolves to the expected five-file business object group and completed the lifecycle cold-backup smoke.

What passed:

```text
The corrected row contains cover_url, video_raw_url, and video_url for the same A380 path group.
All 5 expected roles were found on A380 MinIO with HEAD 200.
All 5 roles transitioned to the 4070S cold tier.
A380 source physical footprint dropped from 312304728 bytes to 14124 bytes.
The 5 cold internal objects were mapped by size + SHA256.
All 5 objects restored into a restore MinIO under original bucket/key.
Source, cold, and restore HTTP HEAD checks all returned 200.
```

Important timing:

```text
The lifecycle scanner took about 756 seconds before the 5 objects changed from STANDARD to the test cold tier.
Rule creation must not be treated as migration completion.
```

## 2. Corrected Row Summary

Important business fields:

| Field | Value |
| --- | --- |
| `id` | `14708948` |
| `company_id` | `100192` |
| `account_id` | `15624` |
| `team_id` | `1079` |
| `group_id` | `2804` |
| `type_id` | `77585` |
| `parent_type_id` | `77578` |
| `state` | `2` |
| `is_del` | `0` |
| `create_time` | `2026-05-20 16:23:59` |
| `update_time` | `2026-06-05 15:25:02` |
| `file_size` | `7167813` |
| `transcode_file_size` | `3431347` |
| `raw_md5` | `ed2a50fa27ca13b4ed4946ac0846c4c9` |
| `transcode_md5` | `ba828ae16ede4d047824614ec0b9214c` |

Direct object fields:

| Role | DB field | DB value |
| --- | --- | --- |
| cover | `cover_url` | `address/sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8.jpg` |
| transcode derivation root | `video_raw_url` | `address/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_h265.MOV` |
| playback video | `video_url` | `address/sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8.mp4` |

Fields related to Liushan or alternate storage were empty:

```text
ls_raw_uri
ls_uri
```

## 3. Business Derivation Rule

Business clarification:

```text
On initial upload:
  video_raw_url = {prefix}.{suffix}

After transcode:
  video_raw_url = {prefix}_h265.{suffix}

Derived source upload:
  {prefix}.{suffix}

Derived watermark source:
  {prefix}_mark919.{suffix}

Derived transcoded video:
  {prefix}_h265.{suffix}
```

For this row:

```text
video_raw_url = address/sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_h265.MOV
```

The source path transform is:

```text
address/sucaiwang/100192/15624/<file>
  -> bucket=sucaiwang
  -> key=sucaiwang/100192/15624/<file>
```

## 4. Five-Role Manifest

Resolved A380 MinIO object manifest:

| Role | Source bucket | Source key | HEAD | Size |
| --- | --- | --- | --- | ---: |
| `source_upload` | `sucaiwang` | `sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae.MOV` | `200` | `107204861` |
| `cover` | `sucaiwang` | `sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8.jpg` | `200` | `290080` |
| `watermark_source` | `sucaiwang` | `sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_mark919.MOV` | `200` | `38044089` |
| `transcoded_video` | `sucaiwang` | `sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae_h265.MOV` | `200` | `7167813` |
| `playback_video` | `sucaiwang` | `sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8.mp4` | `200` | `3431347` |

Total logical bytes:

```text
156138190
```

## 5. Lifecycle Smoke Result

Cold tier:

```text
COLD_4070_VIDEOID5_14708948_20260605
```

Rules were deliberately limited to two stems:

```text
sucaiwang/100192/15624/90c71dc9-aba8-4cee-9d13-7e15b84b68b8
sucaiwang/100192/15624/cf98a722-5227-4bd5-b2d4-b2637661a4ae
```

Result:

```text
WAIT elapsed=756s transitioned=5/5 standard=0 other=0
A380_SOURCE_FOOTPRINT_BEFORE_BYTES 312304728
A380_SOURCE_FOOTPRINT_AFTER_BYTES 14124
COLD_BUCKET_DU_DELTA_BYTES 156145437
MAPPING_MATCHED_COUNT 5/5
RESTORE_OK_FIXED 5/5
```

Detailed result:

```text
videoid-cold-backup-smoke-results-2026-06-05.md
```

## 6. Interpretation

This corrected row supports the intended migration design:

```text
video table row -> five-file manifest: confirmed
video_raw_url derivation -> source/watermark/transcode objects: confirmed
cover_url and video_url -> cover/playback objects: confirmed
MinIO lifecycle transition -> A380 source-space release: confirmed
mapping and restore drill -> confirmed
```

Production caution:

```text
The scanner delay is real. This sample took about 12 minutes 36 seconds to transition after rule creation.
Production tooling must track each videoId as PENDING_RULE, TRANSITIONED, FOOTPRINT_FREED, MAPPED, and RESTORE_VERIFIED instead of assuming one step implies the next.
```
