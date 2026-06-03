# Dual MinIO Hot/Cold IO Test Plan

> Date: 2026-06-03
> Branch: `codex/hot-cold-tiering-analysis`
> Goal: reproduce HDD-only MinIO IO contention, then measure improvement from SSD hot MinIO + HDD cold MinIO.

## 1. Objective

This test is not a production data migration test.

The purpose is to answer one question:

```text
When upload, transcode read, transcode output write, user download, and push read happen in a short high-concurrency window,
how much does separating hot output traffic to SSD reduce HDD pressure and improve storage-service latency?
```

We need two comparable scenarios:

1. Baseline: one HDD MinIO handles all raw files, outputs, downloads, and push reads.
2. New design: HDD MinIO stores raw and archive copies; SSD MinIO stores hot outputs and serves downloads/push reads.

## 2. Selected Server

Use 4070S `172.16.100.217`.

Reasons:

```text
Single server is enough for first controlled IO test.
Root disk is NVMe SSD: WD_BLACK SN770 500GB, 346G currently free.
HDD data disks are online:
  /data/data2 ~11T XFS
  /data/data3 ~11T XFS
Existing production-like services can remain untouched by using isolated ports and directories.
```

Storage allocation:

```text
SSD hot tier:
  200G loopback filesystem on NVMe root disk
  mount path: /mnt/minio-hot-ssd-test

HDD cold tier:
  /data/data2/dual-minio-io-test
```

Why loopback for SSD:

```text
It hard-limits hot tier capacity to 200G.
It avoids scattering test objects across root.
It can be unmounted and deleted cleanly after the test.
The overhead is acceptable for first-stage comparison; final SSD performance tests should use a real SSD data partition.
```

Space risk:

```text
Creating a 200G loopback image reduces root free space from ~346G to ~146G.
This is acceptable for a controlled test, but no other large root writes should run during the benchmark.
```

## 3. Isolation

Do not use existing services:

```text
existing MinIO on 9000/9090
existing SeaweedFS on 8333/8888/9333/8080
existing Docker volumes
production or historical buckets
```

Use isolated containers:

| Role | Container | API port | Console port | Data path |
| --- | --- | ---: | ---: | --- |
| Baseline HDD-only MinIO | `minio_hdd_only_bench` | `19200` | `19290` | `/data/data2/dual-minio-io-test/hdd-only` |
| Dual cold HDD MinIO | `minio_cold_hdd_bench` | `19300` | `19390` | `/data/data2/dual-minio-io-test/cold-hdd` |
| Dual hot SSD MinIO | `minio_hot_ssd_bench` | `19400` | `19490` | `/mnt/minio-hot-ssd-test/minio-hot` |

Use isolated buckets:

```text
hdd-only-raw
hdd-only-output
dual-raw
dual-output-hot
dual-output-archive
```

## 4. Workload Model

Use generated binary test objects, not production files.

Default dataset:

```text
raw object size: 512MiB
object count: 160
raw total: 80GiB
output object size: 512MiB
output total: 80GiB
hot tier peak: about 80GiB plus multipart overhead
```

This fits within the 200G SSD loopback and is large enough to pressure HDD.

If the first test does not create enough pressure, scale to:

```text
object size: 1GiB
object count: 160
raw total: 160GiB
output total: 160GiB
```

Do not exceed 170G hot output in the 200G SSD tier.

## 5. Baseline Scenario: Single HDD MinIO

Endpoint:

```text
http://127.0.0.1:19200
```

All operations hit one HDD-backed MinIO:

```text
1. Upload raw objects -> hdd-only-raw
2. Transcode simulation:
   GET raw from hdd-only-raw
   PUT output to hdd-only-output
3. User download simulation:
   concurrent GET from hdd-only-output
4. Push simulation:
   concurrent GET from hdd-only-output
```

Expected bottleneck:

```text
HDD handles write + sequential read + random read at the same time.
HDD util and await should rise.
PUT/GET latency should degrade under mixed concurrency.
```

Concurrency plan:

| Phase | Operation | Concurrency |
| --- | --- | ---: |
| Raw upload | PUT raw | 8, then 16 |
| Transcode read/write | GET raw + PUT output | 16, then 32 |
| User download | GET output | 32, then 64 |
| Push read | GET output | 32, then 64 |
| Mixed pressure | all above together | combined 64-160 workers |

## 6. Dual MinIO Scenario: HDD Cold + SSD Hot

Endpoints:

```text
HDD MinIO: http://127.0.0.1:19300
SSD MinIO: http://127.0.0.1:19400
```

Operations:

```text
1. Upload raw objects -> HDD dual-raw
2. Transcode simulation:
   GET raw from HDD dual-raw
   PUT output to SSD dual-output-hot
3. User download simulation:
   concurrent GET from SSD dual-output-hot
4. Push simulation:
   concurrent GET from SSD dual-output-hot
5. Archive simulation:
   copy SSD dual-output-hot -> HDD dual-output-archive
   archive copy must be rate-limited
```

Expected improvement:

```text
HDD no longer serves hot output download/push reads.
HDD still handles raw upload, raw transcode read, and archive write.
SSD absorbs hot output write/read pressure.
HDD util/await should drop versus baseline under the same logical workload.
Download/push latency should improve.
```

Archive worker must be rate-limited:

```text
Start with 1-2 archive workers.
Increase only if HDD util stays below threshold.
Do not let archive traffic recreate the same HDD bottleneck.
```

## 7. Metrics

Collect every run:

### System

```text
iostat -xm 1 nvme0n1 sda sdb sdc
pidstat -dur 1
docker stats
df -hT
```

Primary disk metrics:

```text
HDD util %
HDD await
HDD read MB/s
HDD write MB/s
NVMe util %
NVMe await
NVMe read/write MB/s
```

### Application

For each workload phase:

```text
operation count
bytes transferred
duration
throughput MB/s
P50 latency
P95 latency
P99 latency
error count
retry count
```

### Comparison Metrics

| Metric | Baseline | Dual MinIO | Expected direction |
| --- | ---: | ---: | --- |
| HDD util during mixed load | measured | measured | lower |
| HDD await during mixed load | measured | measured | lower |
| Output GET P95 | measured | measured | lower |
| Output GET throughput | measured | measured | higher |
| Transcode simulation throughput | measured | measured | higher or stable |
| Archive lag | n/a | measured | bounded |
| Error rate | measured | measured | no increase |

## 8. Pass Criteria

Functional pass:

```text
all PUT/GET operations complete without data loss
object counts match expected counts
object sizes match expected sizes
sample checksum verification passes
containers restart cleanly after test
cleanup removes test data without affecting existing services
```

Performance pass:

```text
Under the same logical workload, dual MinIO reduces HDD await and improves output GET P95 latency.
```

Minimum useful result:

```text
HDD await reduction >= 30%
output GET P95 latency reduction >= 30%
or output GET throughput improvement >= 50%
```

If improvement is smaller, the architecture may still be useful, but we need to inspect whether:

```text
load generator is the bottleneck
network/CPU is the bottleneck
archive traffic is too aggressive
SSD test path is not representative
object size/concurrency does not match production pressure
```

## 9. Execution Phases

### Phase A: Prepare

```text
1. Create 200G SSD loopback image on 4070S root NVMe.
2. Mount it at /mnt/minio-hot-ssd-test.
3. Create HDD test directories under /data/data2/dual-minio-io-test.
4. Start three isolated MinIO containers.
5. Create test buckets.
6. Install or prepare benchmark client.
```

### Phase B: Baseline HDD-only

```text
1. Generate test objects or stream generated data.
2. Run upload-only warmup.
3. Run mixed workload against HDD-only MinIO.
4. Collect metrics.
5. Verify object counts and sizes.
```

### Phase C: Dual MinIO

```text
1. Use the same workload definition.
2. Raw upload and raw reads go to HDD MinIO.
3. Output writes and hot reads go to SSD MinIO.
4. Archive copy runs in background with controlled concurrency.
5. Collect metrics.
6. Verify object counts and sizes across hot and archive buckets.
```

### Phase D: Compare

```text
1. Produce baseline vs dual summary.
2. Identify bottleneck from iostat and latency.
3. Decide whether 200G SSD tier is enough for next-stage testing.
4. Decide whether to build prototype object state table + Archive Worker.
```

### Phase E: Cleanup

```text
1. Stop isolated MinIO containers.
2. Remove test containers.
3. Remove HDD test directories.
4. Unmount SSD loopback filesystem.
5. Delete 200G loopback image.
6. Confirm existing services are still healthy.
```

## 10. Risks and Controls

| Risk | Control |
| --- | --- |
| Root NVMe fills because of 200G loopback | Reserve exactly 200G and check root free space before starting. |
| Existing MinIO/SeaweedFS ports conflict | Use isolated ports `19200-19490`. |
| Current services affected by CPU or IO pressure | Run first test at lower concurrency; stop if system load affects existing services. |
| HDD archive copy hides hot-tier benefit | Rate-limit archive workers and measure archive separately. |
| Loopback SSD is not final SSD performance | Treat results as architecture signal, not final hardware benchmark. |
| Synthetic objects differ from video files | Use large sequential objects first; add smaller mixed objects later if needed. |

## 11. Decision After First Run

After the first full run, decide:

```text
1. Whether dual MinIO materially reduces HDD await and output GET latency.
2. Whether 200G hot tier is enough for functional testing.
3. Whether we need real SSD data disks before further performance work.
4. Whether to implement object_record/object_location + Archive Worker prototype.
```

Recommended next action:

```text
Approve Phase A preparation on 4070S.
```
