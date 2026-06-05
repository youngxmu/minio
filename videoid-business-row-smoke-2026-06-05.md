# VideoId Business Row Smoke Results - 2026-06-05

> Branch: `codex/cold-backup-tiering-test`
> Input row file: `/Users/zhangyang/Downloads/video.json`
> Business id: `video.id = 14708948`
> Expected source: A380 original MinIO
> Purpose: verify whether one `video` table row can be transformed into a MinIO object manifest for cold-backup migration.

## 1. Result

Smoke result:

```text
PARTIAL / NOT YET PASSED
```

What passed:

```text
The `video` row contains direct object reference fields.
The row can produce a first-pass business object manifest.
A380 host MinIO was healthy during the check.
Signed S3 HEAD verification against A380 MinIO worked for known existing objects.
```

What did not pass:

```text
The 3 object references in this row were not found on A380 host MinIO under the tested bucket/key mappings.
This sample does not yet prove that `videoId -> object group -> A380 MinIO` works.
```

## 2. Row Summary

Important business fields:

| Field | Value |
| --- | --- |
| `id` | `14708948` |
| `name` | `C0871` |
| `company_id` | `96` |
| `account_id` | `9961` |
| `team_id` | `839` |
| `group_id` | `2165` |
| `type_id` | `23613` |
| `parent_type_id` | `19980` |
| `state` | `2` |
| `is_del` | `0` |
| `create_time` | `2024-08-07 17:45:40` |
| `update_time` | `2024-08-12 09:51:27` |
| `file_size` | `3253484` |
| `transcode_file_size` | `4367593` |
| `raw_md5` | `e2940137abdd9bb03d98d8b46dfb1350` |
| `transcode_md5` | `26c9caaa5f77531ba464d32ce1e8acce` |

Direct object fields in this row:

| Role | DB field | DB value |
| --- | --- | --- |
| cover | `cover_url` | `address/sucaiwang/96/9961/d1b093d5-3151-4f4f-908f-8a4d9f3b800f.png` |
| raw or watermark source candidate | `video_raw_url` | `address/sucaiwang/96/9961/69c387bd-1ad9-4e6b-a807-baecc8f68ad4_h265.MP4` |
| playback or transcoded candidate | `video_url` | `address/sucaiwang/96/9961/d1b093d5-3151-4f4f-908f-8a4d9f3b800f.mp4` |

Fields related to Liushan or alternate storage were empty:

```text
ls_raw_uri
ls_uri
```

Observation:

```text
This single `video` row exposes 3 direct object references, not the full 5-role model by itself.
The missing roles may be represented by related tables, derived URLs, or historical pipeline behavior.
```

## 3. A380 Validation Environment

A380 checks:

| Check | Result |
| --- | --- |
| Host | `172.16.100.132` |
| MinIO service | active |
| MinIO health | `http://127.0.0.1:9000/minio/health/ready -> 200` |
| Local `mc` binary | unusable, segfaults even on `mc --version` |
| Validation method | signed S3 HEAD using existing A380 MinIO alias credentials |

S3 HEAD sanity checks passed:

| Bucket/key | Status |
| --- | --- |
| `sucaiwang/ZTS360.png` | `200` |
| `sucaiwang/test_tiering.txt` | `200` |
| `testbucket/tb.txt` | `200` |

This confirms the S3 HEAD verifier was working.

## 4. Candidate Bucket/Key Checks

For each DB value, these mappings were tested:

```text
bucket=sucaiwang, key=<DB value as-is>
bucket=sucaiwang, key=address/96/9961/<filename>
bucket=sucaiwang, key=sucaiwang/96/9961/<filename>
bucket=sucaiwang, key=96/9961/<filename>
bucket=address, key=sucaiwang/96/9961/<filename>
```

S3 HEAD results:

| Role | Candidate count | Result |
| --- | ---: | --- |
| `cover_url` | `5` | all `404` |
| `video_raw_url` | `5` | all `404` |
| `video_url` | `5` | all `404` |

Direct disk-path checks also missed the common candidate paths on all four A380 MinIO data disks:

```text
/data/data{1..4}/sucaiwang/address/sucaiwang/96/9961/<filename>
/data/data{1..4}/sucaiwang/address/96/9961/<filename>
/data/data{1..4}/sucaiwang/sucaiwang/96/9961/<filename>
/data/data{1..4}/sucaiwang/96/9961/<filename>
```

Directory shape observed on A380:

```text
/data/data1/sucaiwang/address/sucaiwang/100192/15624/...
```

The observed A380 address tree exists, but this row's `96/9961` path did not appear in the tested location.

## 5. Interpretation

This row supports the planned manifest concept, but not yet the storage-location assumption.

Current interpretation:

```text
video table row -> direct object references: yes
direct references -> A380 host MinIO objects: not confirmed for this sample
videoId 14708948 as a positive A380 migration smoke sample: not passed
```

Possible reasons:

```text
1. The row belongs to another MinIO/source endpoint, not A380.
2. The business URL path requires a storage-router transform that is not captured by the row alone.
3. The object was deleted, moved, or never existed on A380.
4. The full 5-file video object group is stored across related tables rather than only this `video` row.
5. The expected host is not the A380 host MinIO on `9000`.
```

## 6. Next Checks

After database connection information is confirmed, run a proper business resolver smoke:

```text
1. Query `video` by id = 14708948.
2. Query related tables that may hold source upload, watermark source, transcode, playback, and cover objects.
3. Query or confirm the storage routing table/config that maps `address/sucaiwang/...` to source MinIO endpoint and bucket/key.
4. Produce a manifest with:
   business_video_id
   user_id/account_id/company_id
   file_role
   source_endpoint_alias
   source_bucket
   source_key
   size_bytes
   etag
   sha256 where needed
5. Validate every manifest row with S3 HEAD against the resolved endpoint.
6. Mark the videoId as `COMPLETE`, `PARTIAL`, `ACTIVE`, or `UNKNOWN_LAYOUT`.
```

Acceptance for the next smoke:

```text
At least one videoId resolves to all required object roles.
Each required role returns S3 HEAD 200 on the expected MinIO endpoint.
The endpoint alias is recorded, not inferred from URL text alone.
```
