# Raw SSD First + HDD Archive Test Plan

> Date: 2026-06-03
> Branch: `codex/hot-cold-tiering-analysis`
> Goal: validate whether uploading raw video to SSD first, then archiving to HDD, removes the remaining raw-read HDD bottleneck.

## 1. Background

The 1Gbps full-chain test showed that the current SSD+HDD split improves output write/read and push read, but the raw path still hits HDD:

```text
upload raw -> HDD
transcode read raw <- HDD
output -> SSD
push <- SSD
```

Observed remaining bottleneck:

```text
sda util avg: 72.489%
sda r_await avg: 316.387ms
sda w_await avg: 504.365ms
vmstat wa avg: 37.647%
```

The proposed change is:

```text
upload raw -> SSD
archive raw SSD -> HDD in background
transcode read raw <- SSD
output -> SSD
push <- SSD
archive output SSD -> HDD in background
```

## 2. Production Semantics To Validate

Upload success means:

```text
ssdurl exists and SSD object is readable
```

Durable cold storage means:

```text
hddurl exists after archive finishes and validation passes
```

Deletion rule:

```text
Never delete SSD while hddurl is missing.
Delete raw SSD only after hddurl exists and either transcode is complete or retention time has passed.
Delete output SSD only after output hddurl exists and hot retention policy allows eviction.
```

This creates a temporary risk window where the raw file exists only on SSD. Production must control it with SSD redundancy, archive retry, and alerts.

## 3. Test Scenarios

Use the existing 1Gbps S0/S1 results as baseline:

| Scenario | Raw upload | Transcode raw read | Output write | Push read |
| --- | --- | --- | --- | --- |
| S0 single HDD | HDD | HDD | HDD | HDD |
| S1 output hot SSD | HDD | HDD | SSD | SSD |
| S2 raw/output hot SSD | SSD | SSD | SSD | SSD |

S2 variants:

| Variant | Archive timing | Purpose |
| --- | --- | --- |
| S2-a | Archive after pressure window | Measure best hot-path gain. |
| S2-b | Archive during pressure window, concurrency 1 | Measure default production-like background archive impact. |
| S2-c | Archive during pressure window, concurrency 2/4 | Find HDD saturation threshold. |

Run S2-a first. Only run S2-b/S2-c after S2-a confirms the hot path behaves correctly.

## 4. Storage Layout

Use the isolated 4070S MinIO services:

| Role | Endpoint | Bucket |
| --- | --- | --- |
| HDD-only baseline | `http://172.16.100.217:19200` | existing baseline buckets |
| Cold HDD | `http://172.16.100.217:19300` | `dual-raw`, `dual-output-archive` |
| Hot SSD | `http://172.16.100.217:19400` | `dual-raw-hot`, `dual-output-hot` |

Paths:

```text
Cold HDD data: /data/data2/dual-minio-io-test/cold-hdd
Hot SSD data: /mnt/minio-hot-ssd-test/minio-hot
```

## 5. Workload

Use the same real file as the 1Gbps result:

```text
input.MOV
size_bytes: 142653598
sha256: 22e364a712291b52ab57e8ef233c0fcc473cb969d432f20abc9169cfd03ba0e3
```

Primary S2-a workload:

| Item | Value |
| --- | ---: |
| Object count | 64 |
| Upload concurrency | 64 |
| Transcode simulation concurrency | 64 |
| Push concurrency | 64 |
| Archive concurrency after pressure | 1 |

Pressure window:

```text
A380 PUT live raw -> SSD dual-raw-hot
A770 GET preloaded raw from SSD dual-raw-hot + PUT live output -> SSD dual-output-hot
A380 push GET preloaded output from SSD dual-output-hot
```

After pressure window:

```text
4070S archive raw SSD -> HDD
4070S archive output SSD -> HDD
Register HDD locations in the local index
Evict one hot record and verify fallback push from HDD
```

## 6. Metrics

Collect:

```text
vmstat 1
iostat -y -xm 1 nvme0n1 sda sdb
df -hT /data/data2 /mnt/minio-hot-ssd-test
MinIO health for 19200/19300/19400
client JSON summaries from put-file, transcode-file, push
```

Primary comparison is S2-a vs S1 from `real-video-link1g-results-2026-06-03.md`.

## 7. Success Criteria

S2-a should meet:

```text
errors = 0
transcode throughput improves vs S1
push throughput remains stable or improves vs S1
HDD read MB/s drops materially vs S1
HDD r_await drops materially vs S1
vmstat wa avg drops materially vs S1
```

Suggested thresholds:

```text
HDD rMB/s avg drops >= 70% vs S1
HDD r_await avg drops >= 50% vs S1
transcode throughput improves >= 25% vs S1
push P95 does not regress by more than 10%
```

If upload gets slower, inspect whether the 1Gbps ingress link is the bottleneck. Upload only writes one SSD copy in S2-a, so it should not be worse than S1 unless SSD MinIO or shared network becomes limiting.

## 8. Production Follow-Up If S2 Passes

Production code should add or reuse these fields:

```text
video.ssdurl
video.hddurl
video.ssd_status
video.hdd_status
video.hdd_copy_attempts
video.last_copy_error
video.ssd_delete_after
```

Required workers:

```text
raw archive worker: SSD raw -> HDD raw
output archive worker: SSD output -> HDD output
SSD cleanup worker: deletes only when HDD copy exists and retention condition is met
resolver: transcode/download/push prefers SSD and falls back to HDD
```

Required safety controls:

```text
archive idempotency by videoId/object key
checksum or size validation before hddurl update
retry with backoff
alert on archive lag and failed copies
do not delete SSD without hddurl
```
