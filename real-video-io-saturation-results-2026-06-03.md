# Real Video Local IO Saturation Results - 2026-06-03

> Branch: `codex/hot-cold-tiering-analysis`
> Run id: `local-real-20260603-01`
> Storage server: 4070S `172.16.100.217`
> Test mode: local clients on 4070S, using `127.0.0.1` MinIO endpoints

## 1. Purpose

This run bypassed the current 100Mbps A380/A770/4070S network limit by starting the upload, transcode-simulation, and push clients locally on 4070S.

It is a storage saturation test. It is not a full cross-host production-equivalent chain test.

The goal was to verify whether the single-HDD MinIO case can reproduce high IO wait around the observed production symptom, then replay the same workload against the SSD+HDD design.

## 2. Input File

Source file staged on 4070S:

```text
/root/dual-minio-realfile/input.MOV
```

Observed properties:

```text
size_bytes: 142653598
size: about 136MiB
sha256: 22e364a712291b52ab57e8ef233c0fcc473cb969d432f20abc9169cfd03ba0e3
container: QuickTime / MOV
duration: 18.01s
video: HEVC 3840x2160, about 65Mbps, 59.99fps
audio: AAC mono, 48kHz
```

## 3. Endpoints

| Role | Local endpoint used by clients | Backing storage |
| --- | --- | --- |
| HDD-only MinIO | `http://127.0.0.1:19200` | `/data/data2/dual-minio-io-test/hdd-only` on `sda` HDD |
| Dual cold-HDD MinIO | `http://127.0.0.1:19300` | `/data/data2/dual-minio-io-test/cold-hdd` on `sda` HDD |
| Dual hot-SSD MinIO | `http://127.0.0.1:19400` | `/mnt/minio-hot-ssd-test/minio-hot` on NVMe loopback |

## 4. Workload

Common settings:

| Item | Value |
| --- | ---: |
| Object count | 64 |
| Object size | 142653598 bytes |
| Upload concurrency | 64 |
| Transcode-simulation concurrency | 64 |
| Push concurrency | 64 |
| MinIO errors | 0 in all measured phases |

Each pressure window ran:

```text
local simulated web upload
local simulated transcode: GET raw + PUT output
local simulated push: GET output by videoId index
```

The dual scenario was measured in two variants:

```text
1. archive worker active during the pressure window, concurrency 2
2. no live archive worker during the pressure window
```

## 5. Application Results

### Preload

| Scenario | Phase | Operations | Wall seconds | Throughput MiB/s | Errors |
| --- | --- | ---: | ---: | ---: | ---: |
| HDD-only | PUT raw to HDD | 64 | 53.980 | 161.297 | 0 |
| HDD-only | Transcode simulation to HDD | 64 | 127.732 | 136.330 | 0 |
| Dual | PUT raw to cold-HDD | 64 | 56.291 | 154.677 | 0 |
| Dual | Transcode simulation to hot-SSD | 64 | 63.571 | 273.928 | 0 |

### Pressure Window

| Scenario | Operation | Operations | Wall seconds | Throughput MiB/s | P50 seconds | P95 seconds | P99 seconds | Errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HDD-only | Upload raw to HDD | 64 | 217.517 | 40.028 | 157.004 | 200.237 | 215.115 | 0 |
| HDD-only | Transcode raw HDD -> output HDD | 64 | 268.249 | 64.916 | 262.750 | 267.968 | 268.226 | 0 |
| HDD-only | Push read from HDD | 64 | 260.823 | 33.382 | 193.146 | 240.884 | 260.116 | 0 |
| Dual with live archive | Upload raw to cold-HDD | 64 | 143.873 | 60.518 | n/a | 142.237 | 143.446 | 0 |
| Dual with live archive | Transcode raw cold-HDD -> hot-SSD | 64 | 144.884 | 120.191 | n/a | 144.418 | 144.697 | 0 |
| Dual with live archive | Push read from hot-SSD | 64 | 2.000 | 4353.561 | n/a | 1.986 | 1.988 | 0 |
| Dual with live archive | Archive hot-SSD -> cold-HDD | 64 | 211.565 | 82.309 | n/a | 12.487 | 117.484 | 0 |
| Dual without live archive | Upload raw to cold-HDD | 64 | 140.624 | 61.916 | n/a | 139.928 | 140.112 | 0 |
| Dual without live archive | Transcode raw cold-HDD -> hot-SSD | 64 | 142.001 | 122.631 | n/a | 141.513 | 141.780 | 0 |
| Dual without live archive | Push read from hot-SSD | 64 | 2.592 | 3359.727 | n/a | 2.557 | 2.577 | 0 |

### Same-Concurrency Improvement

Using HDD-only as baseline and dual without live archive as the cleaner hot-path comparison:

| Metric | HDD-only | Dual without live archive | Change |
| --- | ---: | ---: | ---: |
| Upload throughput | 40.028 MiB/s | 61.916 MiB/s | +54.7% |
| Transcode simulation throughput | 64.916 MiB/s | 122.631 MiB/s | +88.9% |
| Push throughput | 33.382 MiB/s | 3359.727 MiB/s | much higher |
| Upload wall time | 217.517s | 140.624s | -35.3% |
| Transcode wall time | 268.249s | 142.001s | -47.1% |
| Push wall time | 260.823s | 2.592s | -99.0% |

## 6. Server Metrics

### VMStat IO Wait

| Scenario | wa avg % | wa p95 % | wa max % | blocked avg | blocked max |
| --- | ---: | ---: | ---: | ---: | ---: |
| HDD-only | 55.291 | 69.0 | 92.0 | 148.19 | 204 |
| Dual with live archive | 40.242 | 67.0 | 97.0 | 78.81 | 188 |
| Dual without live archive | 60.599 | 78.0 | 93.0 | 114.225 | 193 |

### `sda` HDD

| Scenario | util avg % | util p95 % | util max % | rMB/s avg | wMB/s avg | r_await avg ms | r_await p95 ms | w_await avg ms | w_await p95 ms | aqu-sz avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| HDD-only | 100.001 | 100.0 | 100.1 | 65.446 | 65.198 | 763.186 | 1073.0 | 1222.193 | 2065.64 | 63.477 |
| Dual with live archive | 99.493 | 100.0 | 100.1 | 41.231 | 82.432 | 433.215 | 914.68 | 937.844 | 1918.33 | 44.529 |
| Dual without live archive | 99.889 | 100.0 | 100.0 | 61.587 | 61.490 | 626.044 | 855.93 | 1115.326 | 1586.83 | 63.739 |

### `nvme0n1` SSD

| Scenario | util avg % | util max % | write MB/s avg | write MB/s max | w_await avg ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| HDD-only | 0.136 | n/a | negligible | negligible | negligible |
| Dual with live archive | 2.025 | 37.2 | 41.551 | 1089.11 | 1.638 |
| Dual without live archive | 2.655 | n/a | 61.173 | n/a | 1.960 |

### Docker

| Scenario | Container | CPU avg % | CPU max % | Last memory | Last block IO |
| --- | --- | ---: | ---: | --- | --- |
| HDD-only | `minio_hdd_only_bench` | 15.492 | 29.98 | 1.087GiB | 27.4GB / 36.5GB |
| Dual with live archive | `minio_cold_hdd_bench` | 16.482 | 29.21 | n/a | 18.3GB / 27.3GB |
| Dual with live archive | `minio_hot_ssd_bench` | 8.905 | 366.37 | n/a | 23.4GB / 36.5GB |
| Dual without live archive | `minio_cold_hdd_bench` | 14.135 | 23.73 | n/a | 27.4GB / 36.5GB |
| Dual without live archive | `minio_hot_ssd_bench` | 10.404 | 236.44 | n/a | 35.5GB / 54.5GB |

## 7. Space And Health After Run

Storage footprint:

```text
/data/data2/dual-minio-io-test: 35G
/mnt/minio-hot-ssd-test/minio-hot: 26G
/root/dual-minio-io-test/results/local-real-20260603-01: 8.5M
/root/dual-minio-realfile/input.MOV: 137M
```

Filesystem status:

```text
/mnt/minio-hot-ssd-test: 200G total, 171G free
/data/data2: 11T total, 273G used
```

Health:

```text
19200 HDD-only MinIO: 200
19300 cold-HDD MinIO: 200
19400 hot-SSD MinIO: 200
```

Raw result directories on 4070S:

```text
/root/dual-minio-io-test/results/local-real-20260603-01/hdd-only-c64-n64
/root/dual-minio-io-test/results/local-real-20260603-01/dual-c64-n64
/root/dual-minio-io-test/results/local-real-20260603-01/dual-c64-n64-noarchive-live
```

## 8. Conclusion

Single-HDD target was reproduced:

```text
vmstat wa avg: 55.291%
sda util avg: 100.001%
sda r_await avg: 763.186ms
sda w_await avg: 1222.193ms
MinIO errors: 0
```

The SSD+HDD design improved the user-facing hot path at the same concurrency:

```text
Upload raw: 40.028 -> 61.916 MiB/s
Transcode simulation: 64.916 -> 122.631 MiB/s
Push read: 33.382 -> 3359.727 MiB/s
```

However, the HDD was still saturated in the dual design because this workload still puts both live raw upload writes and transcode raw reads on the same single HDD.

Important production implication:

```text
SSD hot tier is valuable for output write/read latency.
It does not by itself remove the raw-file HDD bottleneck.
```

To reduce IO wait under this concurrency, the raw tier needs one or more of:

```text
separate raw-ingest HDD from raw-read HDD
multiple HDDs or erasure/distributed MinIO layout
SSD staging for raw upload
lower raw-upload or transcode-read concurrency
queue-based scheduling that avoids simultaneous raw write/read peaks
```

Archive rule:

```text
Do not run archive aggressively during the live pressure window.
Even archive concurrency 2 kept the HDD at about 100% util in this local run.
Archive should be delayed, rate-limited, or scheduled by current HDD util.
```

Recommended next comparison:

```text
Use the same 64 x input.MOV workload after fixing cross-host links to >= 1Gbps.
Keep archive out of the live window first.
Then add archive back with concurrency 1 and an HDD-util throttle.
```
