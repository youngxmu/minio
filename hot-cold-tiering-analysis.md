# MinIO Hot/Cold Tiering Analysis

> Branch: `codex/hot-cold-tiering-analysis`
> Source document: `/Users/zhangyang/# MinIO 热冷分层存储改造方案（V1.0）`
> Analysis date: 2026-06-03

## Executive Summary

V1.0 的方向是可行的：不要继续依赖 MinIO 内置 tiering / cache / block cache，而是在业务层显式区分原片、转码产物、热数据和归档数据，用数据库状态机控制读写路由和归档。

需要调整的关键点：

1. 当前可用服务器里没有合格的 SSD 热层数据盘。4070S 有大容量数据盘，但这些盘更适合 HDD/大容量目标，不适合验证 SSD 热层性能。
2. A380 现有 MinIO 仍有 COLD transition 失败日志。新方案测试前必须禁用或清理原 MinIO lifecycle/tier 配置，避免后台 transition 干扰测试。
3. 对象表不应只用 `hdd_bucket/hdd_key` 和 `ssd_bucket/ssd_key` 两组字段长期承载所有状态。建议抽象成 `object` + `object_location`，否则后续 SeaweedFS、多个 SSD 节点、多 HDD 池都会继续改表。
4. Archive Worker 必须设计成幂等任务，先校验 HDD 副本，再延迟删除 SSD；不能只按状态字段乐观推进。
5. “SSD MinIO 低冗余”需要明确可丢失边界。素材/成片原片不可丢；转码产物如果可重建，可以低冗余，但归档前丢失会影响下载、推送和重试窗口。

建议第一阶段先做功能闭环，不做性能结论：

```text
A380 HDD MinIO 原片/归档层
4070S 临时热层 MinIO 或 SeaweedFS S3
业务层读写路由 + Archive Worker + 状态机
```

性能结论必须等实际 SSD 数据盘到位后再评估。

## V1.0 Assessment

### Correct Decisions

| Decision | Assessment |
| --- | --- |
| 原片优先落 HDD | 正确。原片是最高安全等级数据。 |
| 转码产物优先走热层 | 正确。下载、推送、短期反复读取主要集中在产物。 |
| 业务层统一 S3 API | 正确。降低后续 MinIO -> SeaweedFS 的迁移成本。 |
| 不优先研究 cache / bcache / LVM cache | 正确。当前问题是冷热生命周期不清晰，而不是单纯缓存命中率。 |
| 新增对象状态表 | 正确，但字段模型需要扩展。 |
| Archive Worker 负责 SSD -> HDD | 正确，但需要补齐幂等、校验、失败恢复。 |

### Gaps

| Gap | Impact | Required fix |
| --- | --- | --- |
| 没有定义读失败 fallback | SSD 删除、归档失败、对象缺失时用户请求不可控 | 读路由必须按状态优先读 SSD，失败后可回退 HDD 或触发重转码。 |
| 没有定义写入事务边界 | MinIO 写成功但 DB 更新失败会产生孤儿对象 | 使用 outbox/reconcile 机制，所有对象写入必须可补偿。 |
| 没有定义归档并发和限速 | Archive Worker 可能反向压垮 HDD | 按 bucket/prefix/user 限流，设置 HDD util / await 水位。 |
| 没有定义删除安全窗口 | 校验后立即删 SSD，回滚窗口不足 | 建议保留 6-24 小时，至少覆盖推送重试窗口。 |
| 没有定义低水位保护 | SSD 满盘后写入会直接失败 | 定义 high/critical watermark，并支持降级直写 HDD。 |
| 容量公式只按重度用户估算 | 多用户峰值、失败重试、归档积压会放大热层需求 | 用 P95/P99 日写入、保留期、归档滞后来建模。 |
| 测试方案没有验收指标 | 压测结果不可决策 | 明确 iowait、await、吞吐、失败率、归档延迟、下载延迟。 |

## Recommended Architecture

### Storage Roles

```text
HDD layer:
  - material_raw
  - final_raw
  - archived material_output
  - archived final_output

Hot layer:
  - material_output during edit/download window
  - final_output during push/retry window
```

Hot layer can be MinIO first, then SeaweedFS later. The business should not depend on either implementation directly.

### Read Path

```text
business request
  -> object metadata lookup
  -> if HOT_READY or SSD_AND_HDD: read hot location first
  -> if hot read fails and HDD copy exists: read HDD fallback
  -> if output is reconstructable and both copies fail: enqueue retranscode
  -> return controlled error only after fallback/retry policy is exhausted
```

Do not expose raw MinIO/SeaweedFS hosts directly to clients for objects whose backend can change. Prefer an internal file service or signed URL generator that selects the backend.

### Write Path

Raw objects:

```text
client upload
  -> HDD layer
  -> commit object metadata as HDD_ONLY
  -> enqueue transcode
```

Output objects:

```text
transcode output
  -> hot layer
  -> commit metadata as SSD_ONLY / HOT_READY
  -> enqueue archive after hot window or push success
```

Archive:

```text
select due object
  -> mark ARCHIVING with lease
  -> copy hot -> HDD
  -> verify size + sha256 or multipart checksum policy
  -> mark SSD_AND_HDD / COLD_READY
  -> wait delete safety window
  -> delete hot copy
  -> mark COLD_ONLY
```

## Data Model Recommendation

V1.0 table:

```sql
video_object(
  hdd_bucket, hdd_key,
  ssd_bucket, ssd_key,
  storage_state
)
```

This is acceptable for a prototype, but not ideal for production. Recommended split:

```sql
object_record (
  id BIGINT PRIMARY KEY,
  biz_type VARCHAR(32) NOT NULL,
  object_type VARCHAR(32) NOT NULL,
  logical_bucket VARCHAR(128) NOT NULL,
  logical_key VARCHAR(1024) NOT NULL,
  size BIGINT NOT NULL,
  sha256 CHAR(64) NULL,
  active_location_id BIGINT NULL,
  storage_state VARCHAR(32) NOT NULL,
  hot_until DATETIME NULL,
  archive_after DATETIME NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL
);
```

```sql
object_location (
  id BIGINT PRIMARY KEY,
  object_id BIGINT NOT NULL,
  backend VARCHAR(32) NOT NULL,
  endpoint_alias VARCHAR(64) NOT NULL,
  bucket VARCHAR(128) NOT NULL,
  object_key VARCHAR(1024) NOT NULL,
  role VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL,
  size BIGINT NULL,
  checksum VARCHAR(128) NULL,
  created_at DATETIME NOT NULL,
  verified_at DATETIME NULL,
  deleted_at DATETIME NULL
);
```

Backend examples:

```text
minio_hdd_a380
minio_hot_4070
seaweedfs_hot
seaweedfs_cold
```

Benefits:

```text
支持多个热层/冷层后端
支持从 MinIO 平滑切换到 SeaweedFS
支持同一 logical object 存在多个物理副本
支持灰度读、回退读、清理孤儿对象
```

## State Machine

Recommended states:

| State | Meaning |
| --- | --- |
| `UPLOADING` | Object write started, not committed. |
| `HDD_ONLY` | Only cold/HDD copy exists. |
| `HOT_ONLY` | Only hot/SSD copy exists, acceptable only for reconstructable output before archive. |
| `HOT_AND_HDD` | Both hot and HDD copies exist and are verified. |
| `ARCHIVE_PENDING` | Object is due for archive. |
| `ARCHIVING` | Archive worker has acquired lease. |
| `COLD_ONLY` | HDD copy exists; hot copy deleted after safety window. |
| `REPAIR_NEEDED` | Metadata says copy exists, but read/checksum failed. |
| `DELETE_PENDING` | User/business requested deletion; physical cleanup pending. |
| `DELETED` | Logical object is deleted. |

Archive worker must use lease columns or a separate job table:

```sql
archive_job(
  id,
  object_id,
  status,
  attempts,
  locked_by,
  locked_until,
  last_error,
  created_at,
  updated_at
)
```

## Capacity Planning

V1.0 formula:

```text
SSD logical capacity = material_output_daily * 2 days + final_output_daily * 1 day
```

Use this as a lower bound. Production sizing should include:

```text
hot_capacity =
  P95(material_output_daily) * material_retention_days
  + P95(final_output_daily) * final_retention_days
  + archive_backlog_hours / 24 * daily_output
  + retry_window_capacity
  + multipart_tmp_capacity
  + 30%-50% headroom
```

For one heavy user in V1.0:

```text
material_output = 500G/day * 2 = 1000G
final_output = 250G/day * 1 = 250G
base = 1.25T
with backlog/headroom = 2T-2.5T usable
```

For 3 heavy users:

```text
base = 3.75T
usable target = 6T-8T
```

For 5 heavy users:

```text
base = 6.25T
usable target = 10T-14T
```

These are usable capacities after redundancy, not raw disk size.

## Current Server Fit

Based on `server-resource-inventory.md`:

| Server | Fit for this project |
| --- | --- |
| A380 | Best HDD/source layer candidate. Has 4 x 15T HDD and restored MinIO. |
| 4070S | Best large target/test host. Has two ~11T data disks, but current disks are capacity disks, not confirmed SSD. |
| A770 | Secondary old MinIO source. No large data disk. |
| dba380 | Not suitable for storage testing. |
| A3802 | Potentially useful if SSH is repaired and storage is confirmed. |
| B580 / 890 | Not usable until reachable. |

Immediate hardware gap:

```text
No confirmed 2T+ SSD data tier is available in the current inventory.
```

Therefore:

```text
Functional tests can start now.
SSD performance tests cannot produce valid conclusions until SSD disks are installed or exposed.
```

## Test Plan

### Phase 0: Clean Existing MinIO Tiering Noise

On A380:

```text
Inspect existing lifecycle/tier rules.
Disable COLD transition rules before new hot/cold tests.
Confirm MinIO logs no longer show repeated transition failures.
```

Reason:

```text
The current A380 MinIO logs still show COLD transition failures.
If this remains active, benchmark and archive tests will be polluted by unrelated background errors.
```

### Phase 1: Functional Prototype

Goal:

```text
Verify business-level routing and archive state machine, not SSD performance.
```

Suggested setup:

```text
HDD layer: A380 MinIO on 9000
Hot layer: 4070S temporary MinIO or SeaweedFS S3 on a non-root data disk
Controller: small archive worker script/service
Metadata: test MySQL/PostgreSQL or local SQLite only for prototype
```

Validation:

```text
1. Upload raw -> HDD_ONLY.
2. Transcode output -> HOT_ONLY.
3. Download reads hot layer.
4. Archive worker copies hot -> HDD and verifies.
5. State becomes HOT_AND_HDD.
6. After safety window, hot object is deleted.
7. State becomes COLD_ONLY.
8. Download falls back to HDD.
9. If hot delete fails, worker retries without corrupting state.
10. If HDD copy checksum fails, state becomes REPAIR_NEEDED and hot copy is retained.
```

### Phase 2: Mixed IO Test

Only run this after SSD tier is real SSD.

Scenarios:

```text
raw upload to HDD
transcode read raw from HDD
output write to SSD
100 concurrent hot downloads from SSD
100 concurrent push reads from SSD
archive worker copying SSD -> HDD under rate limit
```

Required metrics:

```text
HDD util, await, read/write MB/s
SSD util, await, IOPS, read/write MB/s
MinIO PUT/GET latency and error rate
archive queue lag
archive failure rate
download P95/P99 latency
transcode queue delay
push delay
```

Pass criteria:

```text
HDD iowait and await improve versus baseline.
Hot download/push latency improves versus HDD-only baseline.
Archive backlog drains within configured SLA.
No data loss across forced worker restart, MinIO restart, and network interruption tests.
```

## Implementation Decisions Needed

| Decision | Required before implementation |
| --- | --- |
| Hot tier medium | Actual SSD disks, capacity, RAID/erasure policy. |
| Hot output loss tolerance | Whether every output must survive hot tier failure before archive. |
| Public URL strategy | Direct MinIO/SeaweedFS host URLs vs file service / signed URL router. |
| Object key policy | Same bucket/key across HDD and hot tier vs separate buckets. |
| Archive retention | Safety window before deleting hot object. |
| Checksum policy | Full sha256, multipart ETag, sampled checksum, or async checksum. |
| Backpressure policy | What happens when SSD reaches 80/90/95%. |
| Lifecycle policy | Whether MinIO native lifecycle remains disabled permanently. |
| SeaweedFS path | Whether hot tier should already be SeaweedFS to reduce later migration work. |

## Recommended Next Step

Do not start by deploying more storage services. First build a minimal state-machine test:

```text
1. Disable A380 MinIO COLD lifecycle noise.
2. Choose 4070S `/data/data2` or `/data/data3` as temporary hot-layer test path.
3. Deploy a hot-layer S3 endpoint on a non-conflicting port.
4. Create prototype metadata table.
5. Implement archive worker with copy + size/hash verify + delayed delete.
6. Run 100G functional test.
7. Only after correctness is proven, add real SSD and run performance tests.
```

This preserves the SeaweedFS migration option. The storage abstraction and `object_location` model are the important pieces; MinIO-vs-SeaweedFS can remain an implementation detail behind S3-compatible endpoints.
