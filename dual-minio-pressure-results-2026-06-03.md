# Dual MinIO Pressure Test Results - 2026-06-03

> Branch: `codex/hot-cold-tiering-analysis`
> Run id: `pressure-20260603-01`
> Storage server: 4070S `172.16.100.217`
> Client roles: A380 upload/push, A770 transcode simulation

## 1. Environment

Endpoints:

| Role | Endpoint | Backing storage |
| --- | --- | --- |
| HDD-only MinIO | `http://172.16.100.217:19200` | `/data/data2/dual-minio-io-test/hdd-only` on `sda` HDD |
| Dual cold-HDD MinIO | `http://172.16.100.217:19300` | `/data/data2/dual-minio-io-test/cold-hdd` on `sda` HDD |
| Dual hot-SSD MinIO | `http://172.16.100.217:19400` | `/mnt/minio-hot-ssd-test/minio-hot` on NVMe loopback |

Network status:

| Host | Interface | Link |
| --- | --- | --- |
| A380 | `eno1` | 100Mbps full duplex |
| A770 | `eno2` | 100Mbps full duplex |
| 4070S | `eno1` | 100Mbps full duplex |

This run is functionally valid, but it is not a final HDD saturation benchmark. Application throughput is capped by the 100Mbps links.

## 2. Workload

Object size:

```text
128MiB
```

Object count per phase:

```text
8 objects
```

Each scenario ran:

```text
A380 PUT raw
A770 GET raw + PUT output
A380 push task by videoId
```

Dual scenario additionally ran:

```text
4070S local archive worker: hot SSD -> cold HDD
videoId index update: hot + cold locations
fallback smoke: one evicted hot record resolved to HDD and pushed successfully
```

## 3. Application Results

### Preload

| Scenario | Phase | Data | Wall seconds | Throughput MiB/s | Errors |
| --- | --- | ---: | ---: | ---: | ---: |
| HDD-only | A380 PUT raw to HDD | 1GiB | 91.577 | 11.182 | 0 |
| HDD-only | A770 transcode simulation to HDD | 2GiB read+write | 184.727 | 11.087 | 0 |
| Dual | A380 PUT raw to cold-HDD | 1GiB | 91.456 | 11.197 | 0 |
| Dual | A770 transcode simulation to hot-SSD | 2GiB read+write | 182.310 | 11.234 | 0 |

### Pressure Window

| Scenario | Operation | Data | Wall seconds | Throughput MiB/s | P95 seconds | Errors |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| HDD-only | A380 PUT raw | 1GiB | 99.097 | 10.333 | 99.092 | 0 |
| HDD-only | A770 transcode simulation | 2GiB read+write | 270.457 | 7.572 | 270.456 | 0 |
| HDD-only | A380 push read by videoId | 1GiB | 185.934 | 5.507 | 185.930 | 0 |
| Dual | A380 PUT raw to cold-HDD | 1GiB | 96.391 | 10.623 | 96.386 | 0 |
| Dual | A770 transcode simulation to hot-SSD | 2GiB read+write | 273.027 | 7.501 | 273.025 | 0 |
| Dual | A380 push read by videoId from hot-SSD | 1GiB | 186.898 | 5.479 | 186.894 | 0 |
| Dual | 4070S archive hot-SSD -> cold-HDD | 2GiB read+write | 9.281 | 220.663 | 1.916 | 0 |

Push index verification:

| Scenario | Rows | Push sum | Push min | Push max |
| --- | ---: | ---: | ---: | ---: |
| HDD-only | 8 | 8 | 1 | 1 |
| Dual before fallback smoke | 8 | 8 | 1 | 1 |
| Dual after fallback smoke | 8 | 9 | 1 | 2 |

Fallback verification:

```text
Evicted hot for pressure-20260603-01-dual-video-000007.
push --prefer ssd resolved to HDD archive and read 128MiB successfully.
```

## 4. 4070S Disk Metrics

### HDD-only

| Device | Avg read MB/s | Max read MB/s | Avg write MB/s | Max write MB/s | Avg r_await ms | Max r_await ms | Avg w_await ms | Max w_await ms | Avg util % | Max util % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `sda` HDD | 6.285 | 48.060 | 6.393 | 26.080 | 6.278 | 89.590 | 6.269 | 38.840 | 7.287 | 61.700 |
| `nvme0n1` SSD | 0.000 | 0.000 | 0.072 | 4.370 | 0.000 | 0.000 | 0.529 | 6.000 | 0.140 | 2.000 |

### Dual SSD+HDD

| Device | Avg read MB/s | Max read MB/s | Avg write MB/s | Max write MB/s | Avg r_await ms | Max r_await ms | Avg w_await ms | Max w_await ms | Avg util % | Max util % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `sda` HDD | 2.792 | 16.030 | 5.719 | 149.630 | 3.615 | 73.110 | 3.983 | 44.100 | 5.649 | 91.600 |
| `nvme0n1` SSD | 0.000 | 0.110 | 2.890 | 344.180 | 0.003 | 1.000 | 0.596 | 6.060 | 0.237 | 10.600 |

Change from HDD-only to dual:

| Metric | HDD-only | Dual | Direction |
| --- | ---: | ---: | --- |
| HDD avg read MB/s | 6.285 | 2.792 | lower by about 55.6% |
| HDD avg r_await ms | 6.278 | 3.615 | lower by about 42.4% |
| HDD avg w_await ms | 6.269 | 3.983 | lower by about 36.5% |
| HDD avg util % | 7.287 | 5.649 | lower by about 22.5% |
| HDD max util % | 61.700 | 91.600 | higher because archive worker created a short local burst |

## 5. Docker Metrics

### HDD-only

| Container | Avg CPU % | Max CPU % | Last mem | Last net IO | Last block IO |
| --- | ---: | ---: | --- | --- | --- |
| `minio_hdd_only_bench` | 4.655 | 12.700 | 297.1MiB / 30.5GiB | 4.58GB / 3.47GB | 3.22GB / 4.31GB |
| `minio_cold_hdd_bench` | 0.062 | 6.410 | 184.5MiB / 30.5GiB | 22.5kB / 8.54kB | 537kB / 12.6MB |
| `minio_hot_ssd_bench` | 0.053 | 4.790 | 175.7MiB / 30.5GiB | 21.7kB / 7.87kB | 414kB / 24.3MB |

### Dual SSD+HDD

| Container | Avg CPU % | Max CPU % | Last mem | Last net IO | Last block IO |
| --- | ---: | ---: | --- | --- | --- |
| `minio_cold_hdd_bench` | 2.453 | 30.550 | 238.1MiB / 30.5GiB | 3.38GB / 2.29GB | 2.15GB / 3.26GB |
| `minio_hot_ssd_bench` | 2.248 | 12.220 | 267.5MiB / 30.5GiB | 2.28GB / 2.26GB | 2.15GB / 4.38GB |
| `minio_hdd_only_bench` | 0.057 | 5.660 | 216.7MiB / 30.5GiB | 4.58GB / 3.47GB | 3.22GB / 4.34GB |

## 6. Space And Health

After the run:

```text
/data/data2/dual-minio-io-test: 7.1G
/mnt/minio-hot-ssd-test/minio-hot: 2.1G
/root/dual-minio-io-test/results/pressure-20260603-01: 8.9M
```

Filesystem status:

```text
/: 455G total, 146G free
/mnt/minio-hot-ssd-test: 200G total, 195G free
/data/data2: 11T total, about 11T free
```

Health:

```text
19200 HDD-only MinIO: 200
19300 cold-HDD MinIO: 200
19400 hot-SSD MinIO: 200
```

Raw result files on 4070S:

```text
/root/dual-minio-io-test/results/pressure-20260603-01/hdd-only
/root/dual-minio-io-test/results/pressure-20260603-01/dual-ssd-hdd
```

## 7. Conclusion

Functional result:

```text
PASS
```

The complete chain works:

```text
upload raw
transcode read/write
videoId location index
push read
archive hot -> cold
fallback after hot eviction
```

Performance result:

```text
The dual SSD+HDD design reduced average HDD read pressure and await on 4070S,
but application throughput did not improve because A380/A770/4070S are still connected at 100Mbps.
```

Actionable interpretation:

```text
1. Current test proves the chain and shows server-side HDD pressure reduction.
2. Current test does not prove production-grade throughput improvement.
3. The next useful performance run requires at least 1Gbps links, preferably 2.5Gbps or 10Gbps.
4. Archive worker must be rate-limited; this run showed a short HDD util spike to 91.6%.
```

Recommended next run:

```text
Fix network link speed first.
Then repeat the same 8 x 128MiB test to confirm the workload starts to push disk IO.
After that, scale to 160 x 512MiB.
```
