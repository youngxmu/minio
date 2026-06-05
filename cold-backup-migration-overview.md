# Cold Backup MinIO Migration Overview

> Date: 2026-06-05
> Branch: `codex/cold-backup-tiering-test`
> Scope: old independent MinIO capacity relief, cold MinIO migration validation, mapping-based recovery drill.

## 1. Project Goal

The current branch focuses on a cold-backup MinIO migration path, not the earlier SeaweedFS replacement path.

Primary goal:

```text
Move historical object payload bytes away from old full MinIO servers.
Keep the original old MinIO host/bucket/key access path working.
Let new MinIO capacity accept both cold-tier data and normal new uploads where needed.
Use the test process to produce a production migration and recovery plan.
```

Non-goals for this branch:

```text
Do not switch business URLs directly to cold-tier internal object paths.
Do not manually move files from MinIO data directories.
Do not treat MinIO lifecycle transition alone as disaster recovery after source metadata loss.
Do not solve the application namespace redesign problem in this branch.
```

## 2. Recommended Direction

Use MinIO lifecycle transition to a remote MinIO tier for capacity relief.

Recommended production stance:

```text
Capacity relief:
  use MinIO transition from old MinIO to cold MinIO

Normal business access:
  continue reading through old MinIO host/bucket/key

New writes:
  allow newminio1 to accept normal web uploads in isolated business buckets

Migration selection:
  select old business videoId rows first
  resolve every MinIO object that belongs to each videoId
  migrate the complete video object group, not isolated objects by object age

Recovery after old metadata loss:
  generate a dedicated mapping table during migration
  run restore drills before calling it production recovery
  add replication or explicit archive copy if strict DR is required
```

This gives a practical first migration path:

```text
oldminio1/source-bucket/object-key
  -> oldminio1 metadata/stub remains
  -> payload transitions to newminio1 cold-tier bucket
  -> user still reads oldminio1/source-bucket/object-key
```

## 2.1 Business Migration Unit

Do not use "objects older than one year" as the direct migration rule.

Use time only to select candidate `videoId` rows from the business database. The migration unit should be the complete video object group.

Expected MinIO object roles per `videoId`:

| Role | Meaning |
| --- | --- |
| `source_upload` | user-uploaded source file |
| `cover` | cover image |
| `watermark_source` | watermarked original or watermark input file |
| `transcoded_video` | transcoded output video |
| `playback_video` | final playback video |

The exact database columns and object keys must be confirmed from the `video` table and related tables before production. The manifest should record all resolved keys and mark whether each role is required or optional.

Correct selection flow:

```text
1. Query video table for candidate videoId rows, for example videos created more than one year ago.
2. Resolve the expected MinIO objects for each videoId.
3. HEAD every object through the source MinIO endpoint.
4. Classify the videoId as COMPLETE, PARTIAL, ACTIVE, UNKNOWN_LAYOUT, or SKIP.
5. Only migrate COMPLETE videoId groups in the first production waves.
6. Store business_video_id, user_id, file_role, bucket, key, size, ETag, and SHA256 in the source manifest.
```

Why this matters:

```text
If only some objects under one videoId are moved, business reads and later recovery can become inconsistent.
If the source upload is cold but the playback file is hot, access behavior is hard to reason about.
If the cover remains hot but the video payload is cold, recovery drills no longer represent the business object as a whole.
```

## 3. Target Topology

```text
oldminio1  --transition-->  newminio1/tier-oldminio1-sucaiwang
oldminio2  --transition-->  newminio1/tier-oldminio2-sucaiwang
...

web uploads --------->       newminio1/web-upload-sucaiwang

recovery worker ----->       mapping DB + newminio1 cold-tier bucket
                              -> fresh MinIO original bucket/key restore
```

For one new MinIO that carries both roles:

| Bucket class | Example | User-facing | Existing business DB stores it | Recovery mapping DB stores it |
| --- | --- | --- | --- | --- |
| Cold-tier bucket | `tier-oldminio1-sucaiwang` | no | no | yes |
| New upload bucket | `web-upload-sucaiwang` | yes | yes | no, except normal business records |

Rules:

```text
Use separate buckets for cold-tier data and new uploads.
Use separate credentials and policies for the two workloads.
Do not expose cold-tier buckets directly to users.
Do not write cold internal URLs into the current business object table.
Do record cold internal keys in a dedicated recovery mapping table.
```

## 4. Current Test Evidence

| Date | Test | Result | Evidence |
| --- | --- | --- | --- |
| 2026-06-04 | A380 one real object transitioned to 4070S cold MinIO | PASS | `cold-backup-tiering-results-2026-06-04.md` |
| 2026-06-04 | Same-version MinIO 2022 and 2023 isolated tiering | PASS | `minio-tier-version-compat-results-2026-06-04.md` |
| 2026-06-05 | `newminio1` both cold-tier receiver and normal upload node | PASS | `minio-hybrid-role-mapping-recovery-results-2026-06-05.md` |
| 2026-06-05 | A380 real prefix, 15 objects, mapping and restore drill | PASS | `real-prefix-tiering-results-2026-06-05.md` |
| 2026-06-05 | `videoId=14708948`, corrected JSON, complete five-file lifecycle transition and restore drill | PASS | `videoid-cold-backup-smoke-results-2026-06-05.md` |

Important result from the real-prefix test:

```text
15 source objects transitioned successfully.
Source object-path footprint dropped from 635331560 bytes to 144912 bytes.
Cold target grew by 317614802 bytes.
All 15 objects read back through A380 source MinIO.
All 15 objects restored through mapping into a fresh MinIO.
Two rows were ambiguous because two JPG objects had identical payload bytes.
```

Important result from the corrected videoId smoke:

```text
The corrected row resolved all 5 expected objects for videoId 14708948.
The 5 objects totalled 156138190 logical bytes.
All 5 objects transitioned to COLD_4070_VIDEOID5_14708948_20260605 after about 756 seconds.
A380 source physical footprint dropped from 312304728 bytes to 14124 bytes.
4070S cold bucket footprint increased by 156145437 bytes.
Mapping matched 5/5 cold internal objects by size + SHA256.
Restore to a separate MinIO under original bucket/key passed 5/5 checksum checks.
```

Implication:

```text
videoId-based manifest generation is viable when the correct row and path transform are used.
Source-space relief is confirmed for the complete five-file videoId group.
Lifecycle scanner timing is asynchronous; production tooling must wait for storage-class and footprint evidence.
```

## 5. Mapping Decision

The mapping relationship must be processed during each migration wave.

Reason:

```text
The cold MinIO does not store transitioned objects under the original business bucket/key namespace.
The source MinIO metadata knows where the cold object is.
If source metadata is lost and no mapping was generated, the cold bucket alone is not enough for reliable original bucket/key recovery.
```

Required migration-time mapping workflow:

```text
1. Build a videoId-grouped source manifest before transition.
2. Snapshot cold bucket/prefix before transition.
3. Transition a controlled videoId group, prefix, or batch.
4. Snapshot cold bucket/prefix after transition.
5. Diff new cold objects.
6. Read candidates through cold MinIO S3 API.
7. Match by videoId, file role, size, and strong checksum.
8. Mark exact, duplicate, ambiguous, or failed rows.
9. Store verified mapping rows before expanding the wave.
10. Run periodic restore drills using only mapping DB plus cold MinIO.
```

This mapping is a recovery aid. It is not a substitute for a supported backup or replication design until large-scale restore drills pass.

## 6. Version Position

Production-main MinIO release:

```text
RELEASE.2022-11-08T05-27-07Z
```

Current conclusion:

```text
MinIO 2022 can complete this work in a same-version source-to-cold setup.
Do not run production transition from a newer source MinIO to an older cold MinIO.
For each migration wave, align source and cold target MinIO versions unless that exact mix has passed a dedicated smoke test.
Use a healthy mc binary that supports ilm tier and ilm rule commands.
```

## 7. Production Readiness Summary

Ready for the next internal validation:

```text
one source server
one source bucket
one controlled set of candidate videoId rows
same MinIO version on source and cold target
mapping generated during the wave
all expected file roles resolved and verified
restore drill after transition
```

Not ready to do broadly without more work:

```text
all old MinIO servers at once
broad full-bucket lifecycle rules
transition-only disaster recovery claims
mapping after source metadata has already been lost
mixed-version source/cold production waves
```
