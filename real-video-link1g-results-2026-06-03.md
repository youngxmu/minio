# Real Video 1Gbps Chain Test Results - 2026-06-03

> Branch: `codex/hot-cold-tiering-analysis`
> Storage server: 4070S `172.16.100.217`
> Upload/push client: A380 `172.16.100.132`
> Transcode-simulation client: A770 `172.16.100.56`

## 1. Purpose

This run repeats the real `input.MOV` pressure test after the internal network was adjusted from 100Mbps to 1Gbps.

Unlike the previous local-storage saturation run, 4070S did not run the upload simulator. The pressure clients ran on:

```text
A380: web upload + push read
A770: transcode simulation, GET raw + PUT output
4070S: isolated MinIO services + metrics only
```

## 2. Network Check

All three hosts negotiated 1Gbps full duplex:

| Host | Interface | Peer | Link |
| --- | --- | --- | --- |
| A380 | `eno1` | 4070S | 1000Mbps full duplex |
| A770 | `eno2` | 4070S | 1000Mbps full duplex |
| 4070S | `eno1` | A380/A770 | 1000Mbps full duplex |

Python memory-stream throughput:

| Direction | Sender Mbit/s | Receiver Mbit/s |
| --- | ---: | ---: |
| A380 -> 4070S | 942.327 | 940.976 |
| A770 -> 4070S | 943.669 | 941.446 |
| 4070S -> A380 | 943.893 | 941.108 |
| 4070S -> A770 | 943.922 | 941.523 |

## 3. Workload

Input file:

```text
input.MOV
size_bytes: 142653598
sha256: 22e364a712291b52ab57e8ef233c0fcc473cb969d432f20abc9169cfd03ba0e3
```

Common pressure settings:

| Item | Value |
| --- | ---: |
| Object count | 64 |
| Object size | 142653598 bytes |
| Upload concurrency | 64 |
| Transcode simulation concurrency | 64 |
| Push concurrency | 64 |

Run ids:

| Run id | Purpose |
| --- | --- |
| `link1g-real-20260603-02` | Clean full setup, preload, archive after live window, fallback smoke. |
| `link1g-real-20260603-03` | Valid pressure-window rerun with corrected metrics process handling. |

Primary comparison uses `link1g-real-20260603-03`.

## 4. Application Results

### Preload From `link1g-real-20260603-02`

| Scenario | Phase | Wall seconds | Throughput MiB/s | Errors |
| --- | --- | ---: | ---: | ---: |
| HDD-only | A380 PUT raw to HDD | 79.851 | 109.040 | 0 |
| HDD-only | A770 GET raw + PUT output to HDD | 154.564 | 112.664 | 0 |
| SSD+HDD | A380 PUT raw to cold-HDD | 79.480 | 109.548 | 0 |
| SSD+HDD | A770 GET raw from cold-HDD + PUT output to hot-SSD | 150.523 | 115.688 | 0 |

### Pressure Window From `link1g-real-20260603-03`

| Scenario | Operation | Wall seconds | Throughput MiB/s | P50 seconds | P95 seconds | P99 seconds | Errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HDD-only | A380 upload raw to HDD | 261.763 | 33.262 | 197.041 | 249.883 | 261.362 | 0 |
| HDD-only | A770 transcode raw HDD -> output HDD | 275.725 | 63.156 | 267.082 | 274.984 | 275.500 | 0 |
| HDD-only | A380 push read from HDD | 269.108 | 32.355 | 185.529 | 236.474 | 261.437 | 0 |
| SSD+HDD | A380 upload raw to cold-HDD | 118.614 | 73.405 | 104.721 | 117.183 | 118.437 | 0 |
| SSD+HDD | A770 transcode raw cold-HDD -> hot-SSD | 216.674 | 80.369 | 213.709 | 215.527 | 216.095 | 0 |
| SSD+HDD | A380 push read from hot-SSD | 130.169 | 66.889 | 120.604 | 124.090 | 127.885 | 0 |

Improvement at the same concurrency:

| Metric | HDD-only | SSD+HDD | Change |
| --- | ---: | ---: | ---: |
| Upload throughput | 33.262 MiB/s | 73.405 MiB/s | +120.7% |
| Transcode simulation throughput | 63.156 MiB/s | 80.369 MiB/s | +21.4% |
| Push throughput | 32.355 MiB/s | 66.889 MiB/s | +106.7% |
| Upload P95 latency | 249.883s | 117.183s | -53.1% |
| Transcode P95 latency | 274.984s | 215.527s | -27.3% |
| Push P95 latency | 236.474s | 124.090s | -47.5% |

## 5. Server Metrics

### `vmstat`

| Scenario | wa avg % | wa p95 % | wa max % | blocked avg | blocked max |
| --- | ---: | ---: | ---: | ---: | ---: |
| HDD-only | 66.469 | 80 | 94 | 148.693 | 206 |
| SSD+HDD | 37.647 | 77 | 86 | 50.390 | 124 |

### `sda` HDD

| Scenario | util avg % | util p95 % | read MB/s avg | write MB/s avg | r_await avg ms | r_await p95 ms | w_await avg ms | w_await p95 ms | aqu-sz avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HDD-only | 99.936 | 100.0 | 63.320 | 63.231 | 664.758 | 1000.000 | 972.004 | 1445.520 | 63.471 |
| SSD+HDD | 72.489 | 100.0 | 41.616 | 40.274 | 316.387 | 703.760 | 504.365 | 1198.540 | 35.943 |

### `nvme0n1` SSD

| Scenario | util avg % | util p95 % | read MB/s avg | write MB/s avg | r_await avg ms | w_await avg ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HDD-only | 0.126 | 0.6 | 0.000 | 0.073 | 0.025 | 0.527 |
| SSD+HDD | 1.816 | 8.3 | 3.867 | 40.247 | 0.126 | 1.032 |

Docker stats raw logs are retained, but the primary summarized server metrics are `vmstat` and `iostat`.

## 6. Archive And Fallback

Archive was intentionally run after the live pressure window, not during it.

From `link1g-real-20260603-02`:

| Phase | Wall seconds | Throughput MiB/s | P95 seconds | Errors |
| --- | ---: | ---: | ---: | ---: |
| Archive hot-SSD -> cold-HDD, concurrency 1 | 57.008 | 305.460 | 1.253 | 0 |
| Fallback push after evicting one hot record | 1.250 | 108.809 | 1.249 | 0 |

Fallback smoke:

```text
Evicted: link1g-real-20260603-02-dual-video-000063
Resolved prefer=ssd to cold-HDD after hot eviction
Push read succeeded
```

## 7. Space And Health

After the valid pressure rerun:

```text
/data/data2/dual-minio-io-test: 86G
/mnt/minio-hot-ssd-test/minio-hot: 26G
/root/dual-minio-io-test/results/link1g-real-20260603-03: 668K
```

Health:

```text
19200 HDD-only MinIO: 200
19300 cold-HDD MinIO: 200
19400 hot-SSD MinIO: 200
```

Raw result directories:

```text
/root/dual-minio-io-test/results/link1g-real-20260603-02
/root/dual-minio-io-test/results/link1g-real-20260603-03
```

## 8. Conclusion

The 1Gbps network adjustment was sufficient to make the full chain performance-valid.

The single-HDD scenario reproduced the production-like storage symptom:

```text
wa avg: 66.469%
sda util avg: 99.936%
sda r_await avg: 664.758ms
sda w_await avg: 972.004ms
```

The SSD+HDD design materially improved the user-facing path:

```text
upload throughput: +120.7%
push throughput: +106.7%
transcode simulation throughput: +21.4%
```

It also reduced HDD pressure:

```text
sda util avg: 99.936% -> 72.489%
sda r_await avg: 664.758ms -> 316.387ms
sda w_await avg: 972.004ms -> 504.365ms
vmstat wa avg: 66.469% -> 37.647%
```

Remaining bottleneck:

```text
The raw path still shares one HDD for upload writes and transcode raw reads.
The SSD hot tier fixes output write/read pressure, but does not fully solve raw-file HDD contention.
```

Next technical direction:

```text
1. Keep output hot tier on SSD.
2. Do not run archive aggressively during the live window.
3. For higher production concurrency, split or scale the raw tier:
   separate raw ingest/read disks, multiple HDDs, distributed MinIO, or SSD raw staging.
4. If production network is above 1Gbps, repeat with 2.5Gbps/10Gbps before final sizing.
```
