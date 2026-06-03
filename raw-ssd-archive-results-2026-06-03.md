# Raw SSD First + HDD Archive Results - 2026-06-03

> Branch: `codex/hot-cold-tiering-analysis`
> Run id: `rawssd-real-20260603-01`
> Storage server: 4070S `172.16.100.217`
> Upload/push client: A380 `172.16.100.132`
> Transcode-simulation client: A770 `172.16.100.56`

## 1. Purpose

This run validates the proposed flow:

```text
upload raw -> SSD
transcode read raw <- SSD
output -> SSD
push read output <- SSD
archive raw SSD -> HDD after pressure window
archive output SSD -> HDD after pressure window
```

It tests the hot path only. Archive was intentionally delayed until after the pressure window.

## 2. Workload

Input file:

```text
input.MOV
size_bytes: 142653598
sha256: 22e364a712291b52ab57e8ef233c0fcc473cb969d432f20abc9169cfd03ba0e3
```

Settings:

| Item | Value |
| --- | ---: |
| Object count | 64 |
| Upload concurrency | 64 |
| Transcode simulation concurrency | 64 |
| Push concurrency | 64 |
| Archive concurrency after pressure | 1 |

Buckets:

| Role | Endpoint | Bucket |
| --- | --- | --- |
| Raw hot SSD | `http://172.16.100.217:19400` | `dual-raw-hot` |
| Output hot SSD | `http://172.16.100.217:19400` | `dual-output-hot` |
| Raw cold HDD | `http://172.16.100.217:19300` | `dual-raw` |
| Output cold HDD | `http://172.16.100.217:19300` | `dual-output-archive` |

## 3. Application Results

### Preload

| Phase | Wall seconds | Throughput MiB/s | P95 seconds | Errors |
| --- | ---: | ---: | ---: | ---: |
| A380 PUT raw to SSD | 77.964 | 111.679 | 77.957 | 0 |
| A770 GET raw SSD + PUT output SSD | 155.008 | 112.341 | 154.298 | 0 |

### Pressure Window

| Operation | Wall seconds | Throughput MiB/s | P50 seconds | P95 seconds | P99 seconds | Errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A380 upload raw to SSD | 82.825 | 105.123 | 74.151 | 81.296 | 82.304 | 0 |
| A770 transcode raw SSD -> output SSD | 231.774 | 75.133 | 229.001 | 230.461 | 231.763 | 0 |
| A380 push read from SSD | 156.297 | 55.707 | 154.185 | 156.152 | 156.246 | 0 |

### Archive After Pressure

| Phase | Wall seconds | Throughput MiB/s | P95 seconds | Errors |
| --- | ---: | ---: | ---: | ---: |
| Archive raw SSD -> HDD | 48.638 | 358.028 | 1.063 | 0 |
| Archive output SSD -> HDD | 49.027 | 355.186 | 1.075 | 0 |
| Fallback push after output hot eviction | 1.248 | 108.993 | 1.247 | 0 |

Fallback smoke:

```text
Evicted: rawssd-real-20260603-01-video-000063
Resolved prefer=ssd to cold-HDD after hot eviction
Push read succeeded
```

## 4. Server Metrics

### Hot Path Metrics

| Metric | S2-a raw/output SSD |
| --- | ---: |
| vmstat wa avg % | 0.215 |
| vmstat wa p95 % | 1 |
| blocked avg | 0.124 |
| blocked max | 4 |
| sda util avg % | 0.590 |
| sda read MB/s avg | 0.079 |
| sda write MB/s avg | 0.109 |
| sda r_await avg ms | 0.840 |
| sda w_await avg ms | 0.305 |
| nvme0n1 util avg % | 5.069 |
| nvme0n1 read MB/s avg | 18.247 |
| nvme0n1 write MB/s avg | 74.555 |
| nvme0n1 r_await avg ms | 0.412 |
| nvme0n1 w_await avg ms | 0.935 |

### Comparison To Previous 1Gbps Runs

Previous baseline values are from `real-video-link1g-results-2026-06-03.md`.

| Metric | S0 single HDD | S1 output SSD only | S2 raw/output SSD |
| --- | ---: | ---: | ---: |
| Upload throughput MiB/s | 33.262 | 73.405 | 105.123 |
| Transcode throughput MiB/s | 63.156 | 80.369 | 75.133 |
| Push throughput MiB/s | 32.355 | 66.889 | 55.707 |
| vmstat wa avg % | 66.469 | 37.647 | 0.215 |
| sda util avg % | 99.936 | 72.489 | 0.590 |
| sda read MB/s avg | 63.320 | 41.616 | 0.079 |
| sda r_await avg ms | 664.758 | 316.387 | 0.840 |
| sda w_await avg ms | 972.004 | 504.365 | 0.305 |

## 5. Space And Health

After the run:

```text
/data/data2/dual-minio-io-test: 18G
/mnt/minio-hot-ssd-test/minio-hot: 35G
/root/dual-minio-io-test/results/rawssd-real-20260603-01: 340K
```

Health:

```text
19200 HDD-only MinIO: 200
19300 cold-HDD MinIO: 200
19400 hot-SSD MinIO: 200
```

Raw result directory:

```text
/root/dual-minio-io-test/results/rawssd-real-20260603-01
```

## 6. Interpretation

Functional result:

```text
PASS
```

The proposed data lifecycle works in the test harness:

```text
upload raw to SSD
transcode read raw from SSD
write output to SSD
push read output from SSD
archive raw to HDD
archive output to HDD
fallback read from HDD after hot eviction
```

Storage result:

```text
PASS
```

S2-a almost completely removes HDD from the hot path:

```text
sda util avg: 72.489% in S1 -> 0.590% in S2
sda read MB/s avg: 41.616 in S1 -> 0.079 in S2
vmstat wa avg: 37.647% in S1 -> 0.215% in S2
```

Application result:

```text
MIXED at 1Gbps
```

Upload improves strongly because raw upload writes to SSD:

```text
S1 upload: 73.405 MiB/s
S2 upload: 105.123 MiB/s
```

Transcode and push do not improve over S1 in the 1Gbps test:

```text
S1 transcode: 80.369 MiB/s
S2 transcode: 75.133 MiB/s

S1 push: 66.889 MiB/s
S2 push: 55.707 MiB/s
```

Most likely reason:

```text
After HDD pressure is removed, the single 1Gbps 4070S network interface becomes the dominant bottleneck.
The transcode raw GET from SSD and push GET from SSD compete for 4070S egress bandwidth.
The raw upload and transcode output PUT compete for 4070S ingress bandwidth.
```

## 7. Decision

The scheme is architecturally better for storage IO and should remain the preferred production direction, but the current 1Gbps test cannot prove full application throughput improvement for transcode and push.

Recommended next steps:

```text
1. Treat S2 as the storage-IO winner.
2. Do not run S2-b/S2-c archive-during-live tests on 1Gbps yet; the bottleneck has moved to network.
3. Repeat S2-a on 2.5Gbps or 10Gbps before final sizing.
4. If production remains 1Gbps, add bandwidth-aware scheduling:
   limit simultaneous upload/transcode/push concurrency,
   or separate web upload and transcode storage traffic onto different NICs/VLANs.
5. Production code can still adopt the lifecycle, but must include archive retry and SSD retention controls before deleting SSD objects.
```
