# Real Video IO Saturation Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use `/Users/zhangyang/Downloads/input.MOV` as the real test object, raise upload concurrency until single-HDD MinIO shows high IO wait/latency, then run SSD+HDD MinIO with the same concurrency for a valid comparison.

**Architecture:** A380 acts as the web upload and push client, A770 acts as the transcode read/write client, and 4070S runs isolated MinIO services and metrics collection. The test first finds the smallest single-HDD concurrency that produces sustained storage pressure, then replays the same workload against cold-HDD + hot-SSD. If the current 100Mbps links are not fixed, the run is recorded as network-limited and cannot be used as the final performance comparison.

**Tech Stack:** MinIO S3-compatible API, Python benchmark helpers, SQLite `videoId` location index, Docker, `iostat`, `vmstat`, `pidstat`, `docker stats`, `sar` or `ip -s link`.

---

## 1. Input File

Source file:

```text
/Users/zhangyang/Downloads/input.MOV
```

Observed properties:

```text
size: 136MB
size_bytes: 142653598
container: QuickTime / MOV
duration: 18.01s
video: HEVC Main, 3840x2160, yuv420p bt709, about 65Mbps, 59.99fps
audio: AAC mono, 48kHz
rotation metadata: -90 degrees
```

The file is not committed to this repository.

## 2. Required Precondition

Current measured network links:

```text
A380 -> 4070S: 100Mbps full duplex
A770 -> 4070S: 100Mbps full duplex
4070S -> A380/A770: 100Mbps full duplex
```

Measured TCP memory-stream throughput on 2026-06-03:

| Direction | Sender MiB/s | Sender Mbit/s | Receiver MiB/s | Receiver Mbit/s |
| --- | ---: | ---: | ---: | ---: |
| A380 -> 4070S | 11.343 | 95.152 | 11.170 | 93.703 |
| A770 -> 4070S | 11.297 | 94.762 | 11.216 | 94.090 |
| 4070S -> A380 | 11.371 | 95.391 | 11.188 | 93.848 |
| 4070S -> A770 | 11.319 | 94.949 | 11.221 | 94.127 |

Storage inventory relevant to local-bypass tests:

| Host | Relevant disks | Suitability |
| --- | --- | --- |
| 4070S | `sda/sdb` 10.9T HDD, NVMe root | Best current storage target for SSD+HDD design, but remote clients are limited by 100Mbps. |
| A770 | one 476.9G NVMe root, no HDD observed | Not suitable for reproducing single-HDD MinIO contention. Running "web upload" locally here would test SSD/root, not HDD. |
| A380 | four 14.6T HDDs plus NVMe root | Suitable fallback for a single-host local MinIO saturation test if 4070S network cannot be fixed. |

This is not enough to reproduce a production-like storage bottleneck. With 100Mbps, each client is capped around 11MiB/s, so increasing upload concurrency mostly queues on the network rather than saturating 4070S disk IO.

Performance-valid requirement:

```text
A380, A770, and 4070S must negotiate at least 1Gbps.
2.5Gbps or 10Gbps is preferred.
```

Before running the real comparison, verify:

```bash
ip route get 172.16.100.217
iface=$(ip route get 172.16.100.217 | awk '/dev/ {for (i=1;i<=NF;i++) if ($i=="dev") print $(i+1); exit}')
cat /sys/class/net/$iface/speed
cat /sys/class/net/$iface/duplex
iperf3 -s
iperf3 -c 172.16.100.217 -P 8 -t 30
```

Pass criteria before final run:

```text
1Gbps link: iperf3 aggregate >= 900Mbits/sec
2.5Gbps link: iperf3 aggregate >= 2.2Gbits/sec
10Gbps link: iperf3 aggregate >= 8.5Gbits/sec
```

If links remain 100Mbps, run only a functional rehearsal or a separate storage-only saturation test from 4070S local processes. Do not use that as the production-like comparison.

Important decision:

```text
Running the web upload simulator on A770 does not remove the bottleneck while MinIO remains on 4070S.
A770 still reaches 4070S through the same 100Mbps network path.

To remove the bandwidth limit, the upload simulator must run on the same host as the tested MinIO storage,
or the storage server must move to a host whose web/transcode clients are not network-limited.
```

Practical fallback options:

```text
Option A: keep 4070S as storage and fix the 4070S/A380/A770 network links first.
  This is the preferred production-like test.

Option B: run local upload/transcode/push simulators on 4070S against 4070S MinIO.
  This can saturate 4070S HDD, but it is a storage-only test, not a realistic cross-host chain.

Option C: move the isolated MinIO test to A380 and run local upload on A380.
  A380 has multiple HDDs and can reproduce HDD contention locally.
  It will not directly test 4070S hardware, but it can validate the single-HDD vs SSD+HDD architecture under local IO pressure.
```

## 3. Test Objective

Target single-HDD behavior:

```text
server %wa: approach 50% if CPU/core accounting allows it
sda %util: sustained >= 80%
sda await: sustained >= 50ms
MinIO error rate: 0
```

Important interpretation:

```text
On a many-core server, system-wide %wa can be diluted by idle CPU cores.
Use iostat sda %util and await as the primary disk saturation signal.
Use vmstat/top %wa as supporting evidence.
```

The valuable comparison point is:

```text
Find the single-HDD concurrency that creates the target pressure.
Replay exactly the same object count, object size, and concurrency against SSD+HDD.
```

## 4. Tooling Changes Needed Before Execution

Current `scripts/dual_minio_s3bench.py` can generate byte streams and push by `videoId`, but it does not yet upload a real local file repeatedly. Add file-based operations before this test:

### Task 1: Add File PUT Mode

**Files:**
- Modify: `scripts/dual_minio_s3bench.py`

- [ ] **Step 1: Add a file body iterator**

Add this function near `generated_chunks`:

```python
def file_chunks(path, chunk_size=MB):
    with open(path, "rb") as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            yield data
```

- [ ] **Step 2: Add `put_file_object`**

Add this function near `put_object`:

```python
def put_file_object(endpoint, access_key, secret_key, bucket, prefix, index, file_path):
    key = object_key(prefix, index)
    size = os.path.getsize(file_path)
    return request(
        endpoint,
        "PUT",
        s3_object_path(bucket, key),
        access_key,
        secret_key,
        body_iter=file_chunks(file_path),
        length=size,
    )
```

- [ ] **Step 3: Add `put-file` CLI command**

Add this parser section in `build_parser()`:

```python
put_file = sub.add_parser("put-file")
put_file.add_argument("--endpoint", required=True)
put_file.add_argument("--bucket", required=True)
put_file.add_argument("--prefix", default="obj-")
put_file.add_argument("--file", required=True)
put_file.add_argument("--count", type=int, required=True)
put_file.add_argument("--concurrency", type=int, default=8)
put_file.set_defaults(func=cmd_put_file)
```

Add the command implementation:

```python
def cmd_put_file(args):
    access_key, secret_key = get_creds(args)
    run_parallel(
        "put-file",
        args.count,
        args.concurrency,
        lambda index: put_file_object(
            args.endpoint,
            access_key,
            secret_key,
            args.bucket,
            args.prefix,
            index,
            args.file,
        ),
    )
```

- [ ] **Step 4: Verify syntax**

Run:

```bash
python3 -m py_compile scripts/dual_minio_s3bench.py
python3 scripts/dual_minio_s3bench.py put-file --help
```

Expected:

```text
No py_compile output.
put-file help shows --file, --count, --concurrency.
```

### Task 2: Add File-Based Transcode Simulation

**Files:**
- Modify: `scripts/dual_minio_s3bench.py`

The storage pressure part of transcode is:

```text
GET raw object from MinIO
PUT output object to MinIO
```

For this IO test, the output object can reuse `input.MOV` bytes. Actual ffmpeg CPU/GPU encoding is not required for the first storage saturation comparison.

- [ ] **Step 1: Add `transcode-file` command**

Add parser:

```python
transcode_file = sub.add_parser("transcode-file")
transcode_file.add_argument("--src-endpoint", required=True)
transcode_file.add_argument("--src-bucket", required=True)
transcode_file.add_argument("--src-prefix", default="raw-")
transcode_file.add_argument("--dst-endpoint", required=True)
transcode_file.add_argument("--dst-bucket", required=True)
transcode_file.add_argument("--dst-prefix", default="out-")
transcode_file.add_argument("--output-file", required=True)
transcode_file.add_argument("--count", type=int, required=True)
transcode_file.add_argument("--concurrency", type=int, default=8)
transcode_file.set_defaults(func=cmd_transcode_file)
```

Add implementation:

```python
def cmd_transcode_file(args):
    access_key, secret_key = get_creds(args)

    def one(index):
        src = get_object(args.src_endpoint, access_key, secret_key, args.src_bucket, args.src_prefix, index)
        if not src["ok"]:
            return src
        dst = put_file_object(
            args.dst_endpoint,
            access_key,
            secret_key,
            args.dst_bucket,
            args.dst_prefix,
            index,
            args.output_file,
        )
        return {
            "ok": dst["ok"],
            "status": dst["status"],
            "seconds": src["seconds"] + dst["seconds"],
            "sent": dst["sent"],
            "read": src["read"],
            "error": dst["error"],
        }

    run_parallel("transcode-file", args.count, args.concurrency, one)
```

- [ ] **Step 2: Verify syntax**

Run:

```bash
python3 -m py_compile scripts/dual_minio_s3bench.py
python3 scripts/dual_minio_s3bench.py transcode-file --help
```

Expected:

```text
No py_compile output.
transcode-file help shows --output-file.
```

## 5. File Staging

Stage the real video file on both client hosts:

```text
A380: /home/user/dual-minio-realfile/input.MOV
A770: /home/user/dual-minio-realfile/input.MOV
```

Commands from local machine:

```bash
sha256sum /Users/zhangyang/Downloads/input.MOV

ssh user@172.16.100.132 'mkdir -p /home/user/dual-minio-realfile'
scp /Users/zhangyang/Downloads/input.MOV user@172.16.100.132:/home/user/dual-minio-realfile/input.MOV
ssh user@172.16.100.132 'sha256sum /home/user/dual-minio-realfile/input.MOV'

ssh user@172.16.100.56 'mkdir -p /home/user/dual-minio-realfile'
scp /Users/zhangyang/Downloads/input.MOV user@172.16.100.56:/home/user/dual-minio-realfile/input.MOV
ssh user@172.16.100.56 'sha256sum /home/user/dual-minio-realfile/input.MOV'
```

Pass criteria:

```text
All SHA256 values match.
```

## 6. Dataset Size

Use the same object count for HDD-only and SSD+HDD.

Recommended ramp:

| Level | Count | Raw data | Output data | Hot SSD peak | Purpose |
| --- | ---: | ---: | ---: | ---: | --- |
| L1 | 128 | about 17GiB | about 17GiB | about 17GiB | First real-file smoke. |
| L2 | 256 | about 34GiB | about 34GiB | about 34GiB | Medium pressure. |
| L3 | 512 | about 68GiB | about 68GiB | about 68GiB | Primary comparison. |
| L4 | 768 | about 102GiB | about 102GiB | about 102GiB | Only if L3 does not reach target. |

Do not exceed:

```text
hot SSD output <= 150GiB
```

This leaves headroom in the 200G hot SSD loopback.

## 7. Metrics Collection

Run on 4070S for every phase:

```bash
iostat -y -xm 1 nvme0n1 sda sdb sdc
vmstat 1
pidstat -dur 1
docker stats --format '{{json .}}'
df -hT / /mnt/minio-hot-ssd-test /data/data2
iface=$(ip route get 172.16.100.132 | awk '/dev/ {for (i=1;i<=NF;i++) if ($i=="dev") print $(i+1); exit}')
ip -s link show $iface
```

If available:

```bash
mpstat 1
sar -n DEV 1
```

Primary metrics:

```text
vmstat wa
top %wa or mpstat %iowait
sda %util
sda r_await / w_await
sda aqu-sz
MinIO container CPU
MinIO container net IO
MinIO container block IO
operation throughput
P95/P99 latency
error count
```

Pass criteria for single-HDD saturation:

```text
sda %util sustained >= 80%
sda await sustained >= 50ms
server %wa approaches 50% or clearly rises with disk pressure
MinIO errors = 0
```

## 8. Concurrency Ramp

The ramp must find the single-HDD pressure point first.

### L1 Ramp

```text
object count: 128
upload concurrency: 16, 32, 64
transcode concurrency: 16, 32
push concurrency: 32, 64
```

### L2 Ramp

```text
object count: 256
upload concurrency: 64, 96, 128
transcode concurrency: 32, 64
push concurrency: 64, 96
```

### L3 Primary Comparison

```text
object count: 512
use the lowest L1/L2 concurrency that made single-HDD reach target
replay the exact same concurrency against SSD+HDD
```

Stop increasing concurrency when:

```text
sda %util >= 80% for at least 60 seconds
or sda await >= 50ms for at least 60 seconds
or vmstat wa approaches 50%
```

Abort the run if:

```text
MinIO error rate > 0.5%
4070S root free < 80G
hot SSD free < 30G
sda await > 500ms for 60 seconds
load causes existing non-test services to fail health checks
```

## 9. HDD-Only Test

Reset isolated data:

```bash
sudo bash /root/dual-minio-io-test/reset_dual_minio_test.sh --yes --remove-results
```

Restart test MinIO containers and recreate buckets as in `dual-minio-io-test-plan.md`.

Preload raw from A380:

```bash
python3 dual_minio_s3bench.py put-file \
  --endpoint http://172.16.100.217:19200 \
  --bucket hdd-only-raw \
  --prefix real-hdd-raw- \
  --file /home/user/dual-minio-realfile/input.MOV \
  --count 512 \
  --concurrency 64
```

Preload output from A770:

```bash
python3 dual_minio_s3bench.py transcode-file \
  --src-endpoint http://172.16.100.217:19200 \
  --src-bucket hdd-only-raw \
  --src-prefix real-hdd-raw- \
  --dst-endpoint http://172.16.100.217:19200 \
  --dst-bucket hdd-only-output \
  --dst-prefix real-hdd-out- \
  --output-file /home/user/dual-minio-realfile/input.MOV \
  --count 512 \
  --concurrency 64
```

Register push index on A380:

```bash
python3 video_location_index.py \
  --db real-hdd-index.sqlite3 \
  register-range \
  --tier hdd \
  --video-prefix real-hdd-video- \
  --object-prefix real-hdd-out- \
  --count 512 \
  --endpoint-name hdd-only \
  --endpoint http://172.16.100.217:19200 \
  --bucket hdd-only-output \
  --size-bytes 142653598 \
  --make-active
```

Pressure window:

```text
Start 4070S metrics.
Run these concurrently:
  A380 put-file live upload to hdd-only-raw
  A770 transcode-file from hdd-only-raw to hdd-only-output
  A380 push by videoId from hdd-only-output
Stop metrics after the slowest client finishes.
```

Commands:

```bash
python3 dual_minio_s3bench.py put-file \
  --endpoint http://172.16.100.217:19200 \
  --bucket hdd-only-raw \
  --prefix real-hdd-live-raw- \
  --file /home/user/dual-minio-realfile/input.MOV \
  --count 512 \
  --concurrency 64

python3 dual_minio_s3bench.py transcode-file \
  --src-endpoint http://172.16.100.217:19200 \
  --src-bucket hdd-only-raw \
  --src-prefix real-hdd-raw- \
  --dst-endpoint http://172.16.100.217:19200 \
  --dst-bucket hdd-only-output \
  --dst-prefix real-hdd-live-out- \
  --output-file /home/user/dual-minio-realfile/input.MOV \
  --count 512 \
  --concurrency 64

python3 dual_minio_s3bench.py push \
  --index-db real-hdd-index.sqlite3 \
  --video-prefix real-hdd-video- \
  --count 512 \
  --prefer ssd \
  --concurrency 64 \
  --record-push
```

If this does not reach the single-HDD pressure target, increase upload concurrency first:

```text
64 -> 96 -> 128
```

Only increase transcode and push concurrency after upload concurrency alone no longer changes `sda %util`.

## 10. SSD+HDD Test

Use the exact concurrency selected from the HDD-only run.

Preload raw to cold-HDD:

```bash
python3 dual_minio_s3bench.py put-file \
  --endpoint http://172.16.100.217:19300 \
  --bucket dual-raw \
  --prefix real-dual-raw- \
  --file /home/user/dual-minio-realfile/input.MOV \
  --count 512 \
  --concurrency 64
```

Preload hot output:

```bash
python3 dual_minio_s3bench.py transcode-file \
  --src-endpoint http://172.16.100.217:19300 \
  --src-bucket dual-raw \
  --src-prefix real-dual-raw- \
  --dst-endpoint http://172.16.100.217:19400 \
  --dst-bucket dual-output-hot \
  --dst-prefix real-dual-out- \
  --output-file /home/user/dual-minio-realfile/input.MOV \
  --count 512 \
  --concurrency 64
```

Register hot index on A380:

```bash
python3 video_location_index.py \
  --db real-dual-index.sqlite3 \
  register-range \
  --tier ssd \
  --video-prefix real-dual-video- \
  --object-prefix real-dual-out- \
  --count 512 \
  --endpoint-name hot-ssd \
  --endpoint http://172.16.100.217:19400 \
  --bucket dual-output-hot \
  --size-bytes 142653598
```

Pressure window:

```text
Start 4070S metrics.
Run these concurrently:
  A380 put-file live upload to dual-raw on cold-HDD
  A770 transcode-file from dual-raw to dual-output-hot on SSD
  A380 push by videoId from hot SSD
  4070S archive worker hot SSD -> cold HDD with controlled concurrency
Stop metrics after the slowest client finishes.
```

Commands:

```bash
python3 dual_minio_s3bench.py put-file \
  --endpoint http://172.16.100.217:19300 \
  --bucket dual-raw \
  --prefix real-dual-live-raw- \
  --file /home/user/dual-minio-realfile/input.MOV \
  --count 512 \
  --concurrency 64

python3 dual_minio_s3bench.py transcode-file \
  --src-endpoint http://172.16.100.217:19300 \
  --src-bucket dual-raw \
  --src-prefix real-dual-raw- \
  --dst-endpoint http://172.16.100.217:19400 \
  --dst-bucket dual-output-hot \
  --dst-prefix real-dual-live-out- \
  --output-file /home/user/dual-minio-realfile/input.MOV \
  --count 512 \
  --concurrency 64

python3 dual_minio_s3bench.py push \
  --index-db real-dual-index.sqlite3 \
  --video-prefix real-dual-video- \
  --count 512 \
  --prefer ssd \
  --concurrency 64 \
  --record-push

python3 dual_minio_s3bench.py transcode-file \
  --src-endpoint http://127.0.0.1:19400 \
  --src-bucket dual-output-hot \
  --src-prefix real-dual-out- \
  --dst-endpoint http://127.0.0.1:19300 \
  --dst-bucket dual-output-archive \
  --dst-prefix real-dual-archive- \
  --output-file /home/user/dual-minio-realfile/input.MOV \
  --count 512 \
  --concurrency 2
```

Archive worker rule:

```text
Start archive concurrency at 1 or 2.
Do not increase it while sda %util is above 70%.
The archive worker must not recreate the HDD-only bottleneck.
```

After archive completes, register cold locations without changing active tier:

```bash
python3 video_location_index.py \
  --db real-dual-index.sqlite3 \
  register-range \
  --tier hdd \
  --video-prefix real-dual-video- \
  --object-prefix real-dual-archive- \
  --count 512 \
  --endpoint-name cold-hdd \
  --endpoint http://172.16.100.217:19300 \
  --bucket dual-output-archive \
  --size-bytes 142653598
```

Fallback smoke:

```bash
python3 video_location_index.py \
  --db real-dual-index.sqlite3 \
  evict-hot \
  --video-id real-dual-video-000511

python3 dual_minio_s3bench.py push \
  --index-db real-dual-index.sqlite3 \
  --video-id real-dual-video-000511 \
  --prefer ssd \
  --concurrency 1 \
  --record-push
```

Expected:

```text
The evicted object resolves to HDD archive and push succeeds.
```

## 11. Comparison Report

Create:

```text
real-video-io-saturation-results-2026-06-03.md
```

Required tables:

```text
1. network speed and iperf3 results
2. workload size and concurrency
3. application throughput and P95/P99 latency
4. vmstat wa / mpstat iowait
5. iostat sda and nvme0n1 avg/max read/write/await/util
6. docker CPU/net/block IO per MinIO container
7. videoId index push_count and fallback verification
8. space footprint after run
```

Decision rule:

```text
The SSD+HDD plan is valuable if, at the same concurrency:
  HDD avg await drops by >= 30%
  HDD avg util drops by >= 30%
  push P95 latency improves by >= 30%
  transcode simulation throughput is stable or better
  error rate remains 0
```

## 12. Cleanup

Before each full rerun:

```bash
sudo bash /root/dual-minio-io-test/reset_dual_minio_test.sh --yes --remove-results
```

After the final run, keep:

```text
/root/dual-minio-io-test/results/<run-id>
local result markdown document
```

Remove test data if more rounds are not needed:

```bash
sudo bash /root/dual-minio-io-test/reset_dual_minio_test.sh --yes --remove-results
```

Use `--remove-loopback` only when the 200G SSD test mount should be deleted.
