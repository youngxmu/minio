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

Important result from the real-prefix test:

```text
15 source objects transitioned successfully.
Source object-path footprint dropped from 635331560 bytes to 144912 bytes.
Cold target grew by 317614802 bytes.
All 15 objects read back through A380 source MinIO.
All 15 objects restored through mapping into a fresh MinIO.
Two rows were ambiguous because two JPG objects had identical payload bytes.
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
1. Build source manifest before transition.
2. Snapshot cold bucket/prefix before transition.
3. Transition a controlled prefix or batch.
4. Snapshot cold bucket/prefix after transition.
5. Diff new cold objects.
6. Read candidates through cold MinIO S3 API.
7. Match by size and strong checksum.
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
one controlled prefix
same MinIO version on source and cold target
mapping generated during the wave
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
