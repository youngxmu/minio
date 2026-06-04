# MinIO Tier Version Compatibility Results - 2026-06-04

> Branch: `codex/cold-backup-tiering-test`
> Test host: 4070S `172.16.100.217`
> Purpose: verify whether production-era MinIO `RELEASE.2022-11-08T05-27-07Z` and candidate MinIO `RELEASE.2023-12-23T07-19-11Z` can perform same-version remote MinIO tiering.

## 1. Result

Functional result:

```text
PASS
```

Both same-version pairs completed remote MinIO tiering:

| Case | Source MinIO | Cold MinIO | Tier add | Lifecycle rule | Transition | Source read-back |
| --- | --- | --- | --- | --- | --- | --- |
| `v2022` | `RELEASE.2022-11-08T05-27-07Z` | `RELEASE.2022-11-08T05-27-07Z` | PASS | PASS | PASS | PASS |
| `v2023` | `RELEASE.2023-12-23T07-19-11Z` | `RELEASE.2023-12-23T07-19-11Z` | PASS | PASS | PASS | PASS |

Important conclusion:

```text
The production main version RELEASE.2022-11-08T05-27-07Z can complete same-version cold-tier transition in an isolated smoke test.
Upgrading old 64T production sources is not a prerequisite for the next validation step.
```

## 2. Test Boundary

This test used isolated Docker containers and fresh empty data directories on 4070S.

It did not touch:

```text
A380 original MinIO data
4070S current systemd cold MinIO on 9000/9090
any existing 64T production-style data directory
```

Temporary containers were removed after the test. Small data directories and logs remain for inspection:

```text
/data/data2/minio-tier-version-test
/data/data2/minio-tier-version-test/results-20260604-175358.log
/root/minio-tier-version-test-run.sh
```

## 3. Tooling

Management client:

```text
mc version RELEASE.2023-12-23T08-47-21Z
Runtime: go1.21.5 linux/amd64
```

The same `mc` was used to configure both the 2022 and 2023 MinIO servers.

One operational caveat:

```text
mc ilm tier info with the 2023-12 mc container panicked because infocmp was missing in the container image.
mc ilm tier add, mc ilm tier ls, mc ilm rule add, mc ilm rule ls, mc ilm rule export, mc cp, mc stat, and mc cat worked.
The panic did not affect the successful transition test.
```

For production, use a healthy pinned `mc` binary on a management host instead of relying on this exact container image.

## 4. Test Topology

| Case | Role | Endpoint | Container image | Data dir |
| --- | --- | --- | --- | --- |
| `v2022` | source | `http://172.16.100.217:18100` | `quay.io/minio/minio:RELEASE.2022-11-08T05-27-07Z` | `/data/data2/minio-tier-version-test/v2022-src` |
| `v2022` | cold | `http://172.16.100.217:18110` | `quay.io/minio/minio:RELEASE.2022-11-08T05-27-07Z` | `/data/data2/minio-tier-version-test/v2022-cold` |
| `v2023` | source | `http://172.16.100.217:18200` | `quay.io/minio/minio:RELEASE.2023-12-23T07-19-11Z` | `/data/data2/minio-tier-version-test/v2023-src` |
| `v2023` | cold | `http://172.16.100.217:18210` | `quay.io/minio/minio:RELEASE.2023-12-23T07-19-11Z` | `/data/data2/minio-tier-version-test/v2023-cold` |

The remote tier endpoint was configured with the host IP:

```text
http://172.16.100.217:<cold-port>
```

Do not configure container-to-container tier endpoints as `127.0.0.1:<cold-port>`. From the source MinIO container, `127.0.0.1` points back to the source container itself, not to the host or cold container.

## 5. Test Object

| Field | Value |
| --- | --- |
| Bucket | `sourcebucket` |
| Key | `video-test/sample.bin` |
| Size | `33554432` bytes |
| SHA256 | `24ef3a367832f93f91f2ed75440a7c1dbf32af2d7147d63c804ebc671d6e7e36` |

The object was a 32 MiB random file created on the test host.

## 6. v2022 Evidence

Server versions:

```text
Version: RELEASE.2022-11-08T05-27-07Z (go1.19.3 linux/amd64)
```

Tier:

```text
Name        |Type   |Endpoint                     |Bucket            |Prefix  |Region  |Storage-Class
COLD_V2022  |minio  |http://172.16.100.217:18110  |coldbucket-v2022  |v2022/  |        |
```

Lifecycle:

```text
ID: d8gkmehpqccc73fukmi0
Prefix: video-test/sample.bin
Days to tier: 0
Tier: COLD_V2022
```

Transition state:

```text
X-Amz-Storage-Class: COLD_V2022
```

Space:

| Measurement | Source bytes | Cold bytes |
| --- | ---: | ---: |
| Baseline | `33570256` | `14389` |
| After transition | `33814036` | `33813104` |

Read-back:

```text
sha_before=24ef3a367832f93f91f2ed75440a7c1dbf32af2d7147d63c804ebc671d6e7e36
sha_after=24ef3a367832f93f91f2ed75440a7c1dbf32af2d7147d63c804ebc671d6e7e36
bytes=33554432
RESULT PASS
```

Source object path after transition:

```text
/data/data2/minio-tier-version-test/v2022-src/sourcebucket/video-test/sample.bin -> 682 bytes
```

Source `.minio.sys/tmp/.trash` still contained old payload parts immediately after transition:

```text
/data/data2/minio-tier-version-test/v2022-src/.minio.sys/tmp/.trash -> 33560035 bytes
```

## 7. v2023 Evidence

Server versions:

```text
Version: RELEASE.2023-12-23T07-19-11Z (go1.21.5 linux/amd64)
```

Tier:

```text
Name        |Type   |Endpoint                     |Bucket            |Prefix  |Region  |Storage-Class
COLD_V2023  |minio  |http://172.16.100.217:18210  |coldbucket-v2023  |v2023/  |        |
```

Lifecycle:

```text
ID: d8gkmu1pqccc738v5qcg
Prefix: video-test/sample.bin
Days to tier: 0
Tier: COLD_V2023
```

Transition state:

```text
X-Amz-Storage-Class: COLD_V2023
```

Space:

| Measurement | Source bytes | Cold bytes |
| --- | ---: | ---: |
| Baseline | `33566860` | `10993` |
| After transition | `33573914` | `33575605` |

Read-back:

```text
sha_before=24ef3a367832f93f91f2ed75440a7c1dbf32af2d7147d63c804ebc671d6e7e36
sha_after=24ef3a367832f93f91f2ed75440a7c1dbf32af2d7147d63c804ebc671d6e7e36
bytes=33554432
RESULT PASS
```

Source object path after transition:

```text
/data/data2/minio-tier-version-test/v2023-src/sourcebucket/video-test/sample.bin -> 649 bytes
```

Source `.minio.sys/tmp/.trash` still contained old payload parts immediately after transition:

```text
/data/data2/minio-tier-version-test/v2023-src/.minio.sys/tmp/.trash -> 33556513 bytes
```

## 8. Interpretation

What this proves:

```text
RELEASE.2022-11-08T05-27-07Z supports same-version remote MinIO tiering in this isolated test.
RELEASE.2023-12-23T07-19-11Z also supports same-version remote MinIO tiering.
The source endpoint can read back the transitioned object with matching checksum.
The object's source namespace path is reduced to xl.meta scale after transition.
```

What this does not fully prove:

```text
64T production data can be migrated without operational impact.
Production erasure layout and lifecycle scanner behavior are identical to this single-drive Docker smoke.
Source disk free space increases immediately after every transition.
Trash cleanup timing under production load is acceptable.
```

The single-drive Docker test left old payload parts under `.minio.sys/tmp/.trash` immediately after transition. The previous A380 four-disk test showed the selected real object path shrinking from `918056324` bytes to `6408` bytes, so the real production-like erasure test is still the better evidence for actual source object footprint reduction.

## 9. Updated Recommendation

Do not require a broad production upgrade before cold-tier migration validation.

Recommended next step:

```text
1. Build a cold target using the same RELEASE.2022-11-08T05-27-07Z version as production sources.
2. Use a healthy pinned mc that supports ilm tier/rule commands.
3. Run one real production-like object smoke from an old 2022 source to a 2022 cold target.
4. Verify original source URL read-back, checksum, source object path shrink, cold target payload files, and trash cleanup delay.
5. Only consider upgrading if same-version 2022 production-like smoke fails.
```

