# MinIO Migration Server Resource Inventory

> Last updated: 2026-06-03 10:05 CST
> Network: company intranet, direct SSH probe.
> Scope: migration/test servers from the local ops runbook. No passwords are recorded here.

## Summary

| Tier | Server | Current decision |
| --- | --- | --- |
| Primary source | A380 `172.16.100.132` | Keep as restored production-like MinIO source. Do not use as SeaweedFS target for migration speed tests. |
| Best target candidate | 4070S `172.16.100.217` | Has large data disks online again. Best current SeaweedFS target candidate after moving/redeploying SeaweedFS to large disks. |
| Small source/test only | A770 `172.16.100.56` | Keep as isolated old MinIO test source. No 1T+ data disk. |
| GPU test only | dba380 `172.16.101.27` | Useful for multi-GPU transcode checks, not for object-storage migration. |
| Needs access repair | A3802 `172.16.100.234` | Host responds to ping, but SSH and common service ports are refused. |
| Currently unreachable | B580 `172.16.100.239` | No ping / no route during this check. |
| Currently unreachable | 890 `172.16.101.33` | No ping / no route during this check. |

## Capacity View

| Server | Root free | Data disk free | Large-storage suitability |
| --- | ---: | ---: | --- |
| A380 | ~88G | ~56T across 4 x 15T disks | Large capacity, but it is the source MinIO host. Avoid target writes. |
| 4070S | ~74G | ~22.5T across `/data/data1..3` | Best current SeaweedFS target candidate. |
| A770 | ~237G | none | Not suitable for large migration target. |
| dba380 | ~66G | none | Not suitable for migration target. |
| A3802 | unknown | unknown | Needs SSH repair before capacity can be trusted. |
| B580 | unknown | unknown | Currently unreachable. |
| 890 | unknown | unknown | Currently unreachable. |

## Server Details

### A380

| Field | Value |
| --- | --- |
| SSH | `user@172.16.100.132` |
| Hostname | `sucaiwang-test` |
| OS/kernel | Linux `7.0.0-15-generic` |
| CPU | AMD Ryzen 9 9950X, 16 cores / 32 threads |
| Memory | 30Gi total, ~18Gi available |
| GPU | Intel Arc A380, AMD integrated graphics |
| Root disk | 466G ext4, 359G used, 88G free, 81% used |
| Data disks | `/data/data1` 15T, 453G used; `/data/data2` 15T, 295G used; `/data/data3` 15T, 295G used; `/data/data4` 15T, 295G used |
| Active services | `minio-local.service` on `9000/9090`; `minio_migration_test_old1` on `10100/10190`; `transcode`; `auto_cut`; `thumbor` |
| Docker disk use | Images 10.15G; containers 3.26G |

Notes:

```text
Original MinIO was restored as systemd service with /usr/local/bin/minio.
API: http://172.16.100.132:9000
Console: http://172.16.100.132:9090
Isolated test MinIO: http://172.16.100.132:10100
```

Risk:

```text
MinIO logs still show lifecycle transition attempts to COLD failing.
Before migration speed tests, review/disable cold-tier lifecycle rules if they can add noise or retry load.
```

Task recommendation:

```text
Use A380 as the main source MinIO for single-node migration throughput tests.
Do not use it as the SeaweedFS target, even though it has large free capacity, because same-host tests hide real network transfer cost.
```

### 4070S

| Field | Value |
| --- | --- |
| SSH | `root@172.16.100.217` |
| Hostname | `sucaiwang` |
| OS/kernel | Linux `6.17.0-29-generic` |
| CPU | AMD Ryzen 9 9950X, 16 cores / 32 threads |
| Memory | 30Gi total, ~28Gi available |
| GPU | NVIDIA GeForce RTX 4070 SUPER, 12G VRAM |
| Root disk | 455G ext4, 362G used, 74G free, 84% used |
| Data disks | `/data/data1` 932G, 154G used, 778G free; `/data/data2` 11T, 235G used; `/data/data3` 11T, 214G used |
| Active services | Docker `minio_local` on `9000/9090`; SeaweedFS test stack; `gm-service-latest` on `8090` |
| SeaweedFS ports | master `9333`, volume `8080`, filer `8888`, S3 `8333` |
| Docker disk use | Images 9.52G; containers 56M |

Current SeaweedFS mounts:

```text
master -> /data/data1/seaweedfs-test/master
volume -> /data/data1/seaweedfs-test/volume
filer  -> /data/data1/seaweedfs-test/filer
s3 cfg -> /data/data1/seaweedfs-test/s3
```

Task recommendation:

```text
This is the best current SeaweedFS target candidate.
For real migration throughput tests, redeploy or move SeaweedFS volume data to /data/data2 and/or /data/data3.
Avoid writing large migration data to root, because root is already 84% used.
```

### A770

| Field | Value |
| --- | --- |
| SSH | `user@172.16.100.56` |
| Hostname | `sucaiwang` |
| OS/kernel | Linux `6.8.0-107-generic` |
| CPU | AMD Ryzen 9 9950X, 16 cores / 32 threads |
| Memory | 30Gi total, ~28Gi available |
| GPU | Intel Arc A770, AMD integrated graphics |
| Root disk | 466G ext4, 210G used, 237G free, 47% used |
| Data disks | none detected |
| Active services | `transcode`; `minio_migration_test_old2` on `9100/9190`; `MySpeed` on `5216` |
| Docker disk use | Images 22.56G; containers 11M |

Task recommendation:

```text
Use as a second old MinIO source for compatibility and host-only path tests.
Not suitable as a SeaweedFS target or large migration staging host because it has only the root disk.
```

### dba380

| Field | Value |
| --- | --- |
| SSH | `user@172.16.101.27` |
| Hostname | `sucaiwang` |
| OS/kernel | Linux `6.8.0-117-generic` |
| CPU | Intel Core i5-14600K, 20 logical CPUs |
| Memory | 31Gi total, ~30Gi available |
| GPU | Intel UHD 770, 2 x Intel Arc A380 |
| Root disk | 98G ext4, 27G used, 66G free, 29% used |
| Data disks | none detected |
| Active services | `transcode` |

Task recommendation:

```text
Use for multi-GPU transcode or Intel GPU behavior checks.
Do not use for MinIO or SeaweedFS migration storage tests.
```

### A3802

| Field | Value |
| --- | --- |
| SSH | `user@172.16.100.234` |
| Probe result | Ping OK; TCP `22`, `222`, `2222`, `9000`, `9090` refused |
| Hardware | Not updated in this run |
| Storage | Not updated in this run |

Task recommendation:

```text
Repair SSH/service access first.
If this machine has the same large-disk layout as A380, it may become a good alternate SeaweedFS target or backup migration target.
```

### B580

| Field | Value |
| --- | --- |
| SSH | `user@172.16.100.239` |
| Probe result | Ping failed; TCP probes showed timeout / no route / host down |
| Hardware | Not updated in this run |
| Storage | Not updated in this run |

Task recommendation:

```text
Check power/network state before assigning work.
Do not plan migration tasks on it until it is reachable again.
```

### 890

| Field | Value |
| --- | --- |
| SSH | `user@172.16.101.33` |
| Probe result | Ping failed; TCP probes showed timeout / no route / host down |
| Hardware | Not updated in this run |
| Storage | Not updated in this run |

Task recommendation:

```text
Check power/network state before assigning work.
Do not plan migration tasks on it until it is reachable again.
```

## Recommended Task Allocation

1. A380 -> 4070S migration throughput test

```text
Source: A380 restored MinIO on 9000
Target: 4070S SeaweedFS S3 on 8333
Action before test: move/redeploy SeaweedFS volume storage from /data/data1 to /data/data2 or /data/data3.
Reason: this gives a real cross-machine intranet path and enough target capacity.
```

2. A770 -> 4070S compatibility test

```text
Source: A770 isolated MinIO on 9100
Target: 4070S SeaweedFS S3 on 8333
Use small or medium data only.
Reason: A770 has no large data disk, but is useful as a second old MinIO source.
```

3. A3802 follow-up

```text
Priority: medium-high.
Need: fix SSH or confirm alternate access port.
Reason: if it has large data disks, it could reduce risk by providing a second large target/staging host.
```

4. B580 / 890 follow-up

```text
Priority: low for storage migration until reachable.
Need: power/network check.
Reason: they cannot currently be scheduled safely.
```

## Open Risks

| Risk | Impact | Suggested action |
| --- | --- | --- |
| A380 lifecycle transition still retries COLD | Adds background errors/load during source migration | Inspect and disable lifecycle/tier rules before benchmark runs. |
| 4070S root is 84% used | Large Docker/log writes may fill root | Keep migration data on `/data/data2` or `/data/data3`; avoid root-backed Docker volumes. |
| 4070S current SeaweedFS is on `/data/data1` | Only ~778G free in current deployment path | Redeploy SeaweedFS to larger disks for 400-600G+ tests and future scale tests. |
| A3802/B580/890 unavailable or partially unavailable | Reduces fallback choices | Repair access before depending on them in the production plan. |
