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

The complete chain must include the push task after transcode completion:

```text
transcode output ready
  -> update videoId location index
  -> trigger push task
  -> push task resolves videoId, prefers SSD, then GETs the object
```

## 2. Selected Server

Use 4070S `172.16.100.217` as the storage server.

Reasons:

```text
4070S should primarily carry MinIO and disk IO.
Root disk is NVMe SSD: WD_BLACK SN770 500GB, 346G currently free.
HDD data disks are online:
  /data/data2 ~11T XFS
  /data/data3 ~11T XFS
Existing production-like services can remain untouched by using isolated ports and directories.
```

Client roles:

| Role | Server | Purpose |
| --- | --- | --- |
| Storage | 4070S `172.16.100.217` | Run HDD-only MinIO, cold HDD MinIO, hot SSD MinIO. |
| Web upload/download simulator | A380 `172.16.100.132` | Generate upload traffic to 4070S and simulate user downloads. |
| Transcode simulator | A770 `172.16.100.56` | Read raw objects from 4070S and write output objects back to 4070S. |
| Push simulator | A380/A770 | Resolve output by `videoId`, then simulate push download reads. |
| Optional extra transcode simulator | A380 `172.16.100.132` | Add transcode pressure if A770 alone is insufficient. |

This gives a more realistic path:

```text
web upload client on A380
  -> network
  -> 4070S MinIO

transcode simulator on A770
  -> GET raw from 4070S HDD MinIO
  -> PUT output to 4070S HDD-only or SSD-hot MinIO

download/push simulator on A380/A770
  -> resolve videoId from local index
  -> GET output from 4070S
```

Execution constraint:

```text
Do not run upload/download/transcode pressure clients on 4070S during the benchmark.
4070S should only run MinIO, disk metrics collection, and the optional local archive worker.
This keeps 4070S representative of a storage server receiving traffic from web and transcode hosts.
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
1. A380 uploads raw objects -> hdd-only-raw
2. Transcode simulation:
   A770 GET raw from hdd-only-raw
   A770 PUT output to hdd-only-output
3. User download simulation:
   A380 concurrent GET from hdd-only-output
4. Push simulation:
   A770 or A380 resolves videoId from the location index
   A770 or A380 concurrent GET from hdd-only-output
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
1. A380 uploads raw objects -> HDD dual-raw
2. Transcode simulation:
   A770 GET raw from HDD dual-raw
   A770 PUT output to SSD dual-output-hot
3. User download simulation:
   A380 concurrent GET from SSD dual-output-hot
4. Push simulation:
   A770 or A380 resolves videoId from the location index
   A770 or A380 concurrent GET from SSD dual-output-hot, falling back to HDD archive only after hot eviction
5. Archive simulation:
   4070S local archive worker copies SSD dual-output-hot -> HDD dual-output-archive
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
| Push GET P95 | measured | measured | lower |
| Output GET throughput | measured | measured | higher |
| Push GET throughput | measured | measured | higher |
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
6. Copy benchmark client script to A380, A770, and 4070S.
7. Initialize the videoId location index.
8. Run a small end-to-end smoke test:
   A380 PUT raw -> 4070S HDD MinIO
   A770 GET raw + PUT output -> 4070S hot MinIO
   update videoId index -> active_tier=ssd
   A380 push resolves videoId -> GET output from 4070S hot MinIO
```

### Phase B: Baseline HDD-only

```text
1. Generate test objects or stream generated data.
2. Run upload-only warmup.
3. Register HDD-only output locations in the videoId index.
4. Run mixed workload against HDD-only MinIO.
5. Run push simulation by videoId.
6. Collect metrics.
7. Verify object counts, object sizes, and push read counts.
```

### Phase C: Dual MinIO

```text
1. Use the same workload definition.
2. Raw upload and raw reads go to HDD MinIO.
3. Output writes and hot reads go to SSD MinIO.
4. Transcode completion registers hot SSD output in the videoId index.
5. Push simulation resolves videoId and prefers SSD.
6. Archive copy runs in background with controlled concurrency.
7. Archive completion registers HDD copy without switching active_tier while SSD exists.
8. Collect metrics.
9. Verify object counts, object sizes, push read counts, and index state.
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
4. Remove hot SSD test objects.
5. Remove the videoId index DB for the run.
6. Optionally remove result logs.
7. Optionally unmount SSD loopback filesystem and delete the 200G image.
8. Confirm existing services are still healthy.
```

## 10. Risks and Controls

| Risk | Control |
| --- | --- |
| Root NVMe fills because of 200G loopback | Reserve exactly 200G and check root free space before starting. |
| Existing MinIO/SeaweedFS ports conflict | Use isolated ports `19200-19490`. |
| Current services affected by CPU or IO pressure | Run first test at lower concurrency; stop if system load affects existing services. |
| HDD archive copy hides hot-tier benefit | Rate-limit archive workers and measure archive separately. |
| Push task reads from the wrong tier | Resolve every push by `videoId`; record resolved tier and push count. |
| Stale index data affects later rounds | Use the reset script before every full test round. |
| Multi-round tests fill SSD/HDD | Clean test buckets, index DB, and results after each round. |
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
Run Phase B/C calibration with small generated objects, then scale to the default 80GiB workload.
```

## 12. Phase A Execution Record

Date: 2026-06-03

Storage server:

```text
4070S 172.16.100.217
```

Client roles used:

```text
A380 172.16.100.132:
  web upload simulator
  web download simulator

A770 172.16.100.56:
  transcode simulator
  optional output read/push simulator
```

Isolated test endpoints:

| Role | Endpoint | Backing path |
| --- | --- | --- |
| Baseline HDD-only MinIO | `http://172.16.100.217:19200` | `/data/data2/dual-minio-io-test/hdd-only` |
| Dual cold HDD MinIO | `http://172.16.100.217:19300` | `/data/data2/dual-minio-io-test/cold-hdd` |
| Dual hot SSD MinIO | `http://172.16.100.217:19400` | `/mnt/minio-hot-ssd-test/minio-hot` |

Prepared storage:

```text
SSD loopback image: /opt/dual-minio-io-test/hot-ssd-200g.img
SSD mount: /mnt/minio-hot-ssd-test
SSD filesystem: XFS
SSD capacity: 200G total, 197G free after smoke

HDD path: /data/data2/dual-minio-io-test
HDD filesystem: XFS
HDD capacity: 11T total, about 11T free after smoke

Root filesystem after loopback reservation: 455G total, 146G free
```

Containers started:

```text
minio_hdd_only_bench    19200/19290
minio_cold_hdd_bench   19300/19390
minio_hot_ssd_bench    19400/19490
```

Buckets created:

```text
hdd-only-raw
hdd-only-output
dual-raw
dual-output-hot
dual-output-archive
```

Smoke result:

```text
PASS

A380 PUT raw -> 4070S HDD-only MinIO:
  2 x 1MiB, errors=0

A380 PUT raw -> 4070S cold-HDD MinIO:
  2 x 1MiB, errors=0

A770 GET raw + PUT output -> 4070S HDD-only MinIO:
  2 x 1MiB, errors=0

A770 GET raw from cold-HDD + PUT output to hot-SSD:
  2 x 1MiB, errors=0

A380 GET output from HDD-only and hot-SSD:
  2 x 1MiB each, errors=0

A770 GET hot output:
  2 x 1MiB, errors=0

A380 push simulation by videoId -> hot SSD MinIO:
  1 x 1MiB, errors=0
  push_count updated to 1
```

Benchmark helper location:

```text
local repo: scripts/dual_minio_s3bench.py
4070S: /root/dual-minio-io-test/dual_minio_s3bench.py
A380: /home/user/dual-minio-io-test/dual_minio_s3bench.py
A770: /home/user/dual-minio-io-test/dual_minio_s3bench.py
```

Credential handling:

```text
Test-only credentials are stored in env files on the test hosts.
Do not commit credentials to this repository.
```

## 13. Calibration Record

Date: 2026-06-03

Run id:

```text
calib-20260603-01
```

Scale:

```text
Preload raw:
  8 x 128MiB for HDD-only
  8 x 128MiB for dual cold-HDD

Preload output:
  4 x 128MiB for HDD-only
  4 x 128MiB for dual hot-SSD

Mixed window:
  A380 PUT 4 x 128MiB
  A770 GET raw + PUT output, 4 x 128MiB
  A380 GET output, 4 x 128MiB
  A770 GET output, 4 x 128MiB
  dual only: 4070S local archive worker, 4 x 128MiB, concurrency=1
```

Preload result:

| Phase | Path | Operations | Wall seconds | Throughput MiB/s | Errors |
| --- | --- | ---: | ---: | ---: | ---: |
| Raw upload | A380 -> HDD-only | 8 x 128MiB | 107.081 | 9.563 | 0 |
| Raw upload | A380 -> dual cold-HDD | 8 x 128MiB | 99.491 | 10.292 | 0 |
| Output preload | A770 HDD-only transcode simulation | 4 x 128MiB | 91.253 | 11.222 | 0 |
| Output preload | A770 dual transcode simulation | 4 x 128MiB | 108.742 | 9.417 | 0 |

Mixed workload result:

| Scenario | Operation | Operations | Wall seconds | Throughput MiB/s | P95 seconds | Errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| HDD-only | A380 PUT raw | 4 x 128MiB | 49.884 | 10.264 | 49.882 | 0 |
| HDD-only | A770 transcode simulation | 4 x 128MiB | 181.806 | 5.632 | 181.804 | 0 |
| HDD-only | A380 GET output | 4 x 128MiB | 138.947 | 3.685 | 138.946 | 0 |
| HDD-only | A770 GET output | 4 x 128MiB | 141.473 | 3.619 | 141.472 | 0 |
| Dual | A380 PUT raw to cold-HDD | 4 x 128MiB | 47.902 | 10.688 | 47.901 | 0 |
| Dual | A770 transcode simulation to hot-SSD | 4 x 128MiB | 184.205 | 5.559 | 184.203 | 0 |
| Dual | A380 GET hot output | 4 x 128MiB | 140.703 | 3.639 | 140.701 | 0 |
| Dual | A770 GET hot output | 4 x 128MiB | 138.765 | 3.690 | 138.764 | 0 |
| Dual | 4070S archive hot -> cold | 4 x 128MiB | 3.439 | 297.733 | 1.313 | 0 |

4070S disk metrics:

| Scenario | Device | Avg read MB/s | Avg write MB/s | Avg r_await ms | Avg w_await ms | Avg util % |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| HDD-only | `sda` HDD | 7.232 | 5.315 | 6.348 | 4.643 | 7.439 |
| HDD-only | `nvme0n1` SSD | 0.001 | 0.100 | 0.030 | 0.520 | 0.139 |
| Dual | `sda` HDD | 2.733 | 5.036 | 4.526 | 2.815 | 4.874 |
| Dual | `nvme0n1` SSD | 0.000 | 2.324 | 0.000 | 0.581 | 0.213 |

Network link check:

| Host | Interface | Current link |
| --- | --- | --- |
| A380 `172.16.100.132` | `eno1` | 100Mbps full duplex |
| A770 `172.16.100.56` | `eno2` | 100Mbps full duplex |
| 4070S `172.16.100.217` | `eno1` | 100Mbps full duplex |

Interpretation:

```text
This calibration is functionally valid but not performance-valid for the HDD saturation question.

Observed application throughput is close to the 100Mbps network ceiling.
4070S HDD util stayed low in both scenarios, so the test did not reproduce the target "single HDD MinIO saturated by mixed IO" condition.

Dual MinIO reduced 4070S HDD read traffic and await in the sample, but user-visible GET and transcode throughput did not improve because the client/storage network path is the dominant bottleneck.
```

Required adjustment before a full 80GiB run:

```text
Fix or replace the network path so A380, A770, and 4070S negotiate at least 1Gbps.
Prefer 2.5Gbps or 10Gbps if the production bottleneck is HDD IO rather than 100Mbps access links.

Do not run the 80GiB workload on the current 100Mbps links; it will mostly measure network ceiling and consume too much time.
```

Current test footprint:

```text
/data/data2/dual-minio-io-test: 4.6G
/mnt/minio-hot-ssd-test/minio-hot: 1.1G
/root/dual-minio-io-test/results/calib-20260603-01: 5.9M
```

## 14. Missing Chain Items Added

The next test round must use these additions:

```text
1. A770 writes transcode output.
2. The test harness registers videoId -> output location.
3. Push simulation is triggered after output registration.
4. Push simulation resolves videoId with prefer=ssd.
5. Push simulation GETs from SSD when hot_present=1.
6. Archive worker copies SSD output to HDD and registers cold location.
7. Hot cleanup can evict SSD only after cold_present=1.
8. Later push reads fall back to HDD after hot eviction.
```

Scripts:

| Script | Purpose |
| --- | --- |
| `scripts/video_location_index.py` | Maintains the SQLite `videoId` location index for tests. |
| `scripts/dual_minio_s3bench.py push` | Simulates push download IO by resolving `videoId` from the index. |
| `scripts/reset_dual_minio_test.sh` | Cleans isolated MinIO test data, index DB, and optional result logs. |

Default index paths:

```text
4070S: /root/dual-minio-io-test/video-location-index.sqlite3
A380/A770 push clients: /home/user/dual-minio-io-test/video-location-index.sqlite3
```

For controlled benchmark runs, the index can be generated deterministically on the push client before the push phase. Production must replace this with one authoritative Java-accessible store.

Push simulation example:

```bash
python3 video_location_index.py \
  --db video-location-index.sqlite3 \
  register-range \
  --tier ssd \
  --video-prefix round01-dual-video- \
  --object-prefix round01-dual-out- \
  --count 160 \
  --endpoint-name hot-ssd \
  --endpoint http://172.16.100.217:19400 \
  --bucket dual-output-hot \
  --size-bytes 536870912

python3 dual_minio_s3bench.py push \
  --index-db video-location-index.sqlite3 \
  --video-prefix round01-dual-video- \
  --count 160 \
  --prefer ssd \
  --concurrency 64 \
  --record-push
```

Reset before a new full round:

```bash
sudo bash scripts/reset_dual_minio_test.sh --yes --remove-results
```

Use `--remove-loopback` only when the 200G SSD loopback image should be removed. Normal multi-round testing should keep the loopback mounted and only clean object data and the index DB.

Validation completed:

```text
A380 push smoke:
  registered smoke-dual-video-000000 -> smoke-dual-out-000000.bin
  resolved prefer=ssd -> http://172.16.100.217:19400 / dual-output-hot
  push GET 1 x 1MiB, errors=0
  push_count=1

4070S reset dry-run:
  verified container removal commands
  verified HDD test data cleanup paths
  verified hot SSD test data cleanup path
  verified index DB cleanup path
  verified optional results cleanup path
  no deletion executed without --yes
```
