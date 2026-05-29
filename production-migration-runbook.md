# MinIO 到 SeaweedFS 生产迁移 Runbook

版本日期：2026-05-27

## 1. 迁移原则

本 runbook 基于 2026-05-27 三台服务器隔离测试结果整理。

核心原则：

```text
新写入先切到 SeaweedFS
旧 MinIO 停写或只读
用 mc mirror 批量迁移
按 key + size 全量对账
按样本 sha256 校验内容
灰度切读
旧 MinIO 只读保留
```

本方案不覆盖完整 S3 高级能力迁移，例如 versioning、object lock、retention、legal hold、replication、notification、复杂 ACL、复杂 bucket policy。

## 2. 生产前置检查

### 2.1 旧 MinIO 数据盘点

每个旧 MinIO 执行：

```bash
mc ls old1
mc ls old2
```

按 bucket 生成清单：

```bash
mc ls --recursive --json old1/BUCKET \
  | jq -r 'select(.key != null) | [.key, .size] | @tsv' \
  | LC_ALL=C sort > old1.BUCKET.manifest
```

统计对象数与总大小：

```bash
count=$(wc -l < old1.BUCKET.manifest | tr -d ' ')
bytes=$(awk -F '\t' '{sum += $2} END {print sum + 0}' old1.BUCKET.manifest)
echo "objects=$count bytes=$bytes"
```

### 2.2 路径冲突扫描

SeaweedFS 不支持同一路径同时既是文件又是目录。迁移前必须扫描：

```bash
cut -f1 old1.BUCKET.manifest | LC_ALL=C sort > old1.BUCKET.keys.sorted

awk '
  NR > 1 && index($0, prev "/") == 1 {
    print "CONFLICT\t" prev "\t" $0
  }
  { prev=$0 }
' old1.BUCKET.keys.sorted > old1.BUCKET.key_conflicts.txt
```

如果 `key_conflicts.txt` 非空，先决策冲突处理策略，不进入批量迁移。

常见策略：

| 策略 | 适用场景 |
| --- | --- |
| 重命名文件型 key | 冲突数量少 |
| 迁移时记录 old_key -> new_key | 业务数据库中有持久引用 |
| 保留旧 MinIO fallback | 极少数冷数据 |

## 3. SeaweedFS 生产部署要求

测试阶段用的是单机 SeaweedFS。生产不要照搬单机架构。

建议生产拓扑：

```text
Master x 3
Volume Server x N
Filer x 2
S3 Gateway x 1~2，仅迁移期或兼容期使用
Filer Metadata Store 使用高可用 MySQL / PostgreSQL / Redis / Cassandra 等
```

硬性要求：

```text
不要使用单副本承载生产数据
Filer metadata store 必须有备份
S3 Gateway 必须显式配置认证
Volume Server 的 -max 需要按容量和 collection 数量估算
```

## 4. 迁移期 SeaweedFS S3 配置

测试发现 SeaweedFS S3 Gateway 不配置 credentials 时，`mc mirror` 会失败：

```text
Signed request requires setting up SeaweedFS S3 authentication
```

迁移期应显式配置 `s3.json`：

```json
{
  "identities": [
    {
      "name": "migration-admin",
      "credentials": [
        {
          "accessKey": "REPLACE_WITH_ACCESS_KEY",
          "secretKey": "REPLACE_WITH_SECRET_KEY"
        }
      ],
      "actions": ["Admin", "Read", "List", "Tagging", "Write"]
    }
  ]
}
```

凭据不要写入仓库。生产部署时通过私有配置管理或运维密钥系统分发。

## 5. 切写流程

推荐顺序：

```text
1. 新上传全部写 SeaweedFS。
2. 旧文件继续从旧 MinIO 读。
3. 旧 MinIO 停写或只读，只保留 GET / HEAD / LIST。
4. 开始迁移历史对象。
```

如果业务有文件表，建议增加或复用字段：

```sql
ALTER TABLE file_info ADD COLUMN storage_backend VARCHAR(32) DEFAULT 'legacy';
ALTER TABLE file_info ADD COLUMN migrated_at DATETIME NULL;
```

示例值：

```text
minio_old_1
minio_old_2
seaweedfs
```

## 6. 批量迁移

配置 alias：

```bash
read -rsp "old1 access key: " OLD1_AK; echo
read -rsp "old1 secret key: " OLD1_SK; echo
read -rsp "seaweedfs access key: " SW_AK; echo
read -rsp "seaweedfs secret key: " SW_SK; echo

mc alias set old1 "$OLD1_ENDPOINT" "$OLD1_AK" "$OLD1_SK" --api S3v4
mc alias set sw "$SW_ENDPOINT" "$SW_AK" "$SW_SK" --api S3v4
```

迁移 bucket：

```bash
mc mb sw/TARGET_BUCKET || true

mc mirror \
  --overwrite \
  --retry \
  --summary \
  old1/SOURCE_BUCKET \
  sw/TARGET_BUCKET
```

生产建议按 bucket、prefix 或用户分批执行。大规模迁移时先从低风险、冷数据开始。

### 6.1 只换 host、不改相对路径的合并迁移

如果最终目标是：

```text
old1: http://OLD1_HOST/BUCKET/<object-key>
new:  http://SEAWEEDFS_HOST/BUCKET/<object-key>

old2: http://OLD2_HOST/BUCKET/<object-key>
new:  http://SEAWEEDFS_HOST/BUCKET/<object-key>
```

这表示 old1 和 old2 的同名 bucket 会合并到 SeaweedFS 的同一个 bucket。该模式能最大限度降低业务 URL 改造成本，但有一个硬风险：

```text
old1/BUCKET/a.jpg
old2/BUCKET/a.jpg
```

如果两个对象内容不同，迁移到：

```text
sw/BUCKET/a.jpg
```

只能保留一个对象，另一个会被覆盖，除非业务提前定义冲突处理策略。

因此，执行同 bucket 合并迁移前必须先做跨源重复 key 扫描：

```bash
cut -f1 old1.BUCKET.manifest | LC_ALL=C sort > old1.BUCKET.keys
cut -f1 old2.BUCKET.manifest | LC_ALL=C sort > old2.BUCKET.keys

comm -12 old1.BUCKET.keys old2.BUCKET.keys > BUCKET.duplicate.keys
```

判断标准：

```text
BUCKET.duplicate.keys 为空：可以合并迁移到同一个 SeaweedFS bucket。
BUCKET.duplicate.keys 非空：必须对重复 key 做 size 和 checksum 比对。
```

重复 key 处置：

| 情况 | 处理方式 |
| --- | --- |
| size 一致且 checksum 一致 | 可视为同一对象，允许合并 |
| size 不一致 | 不允许直接合并 |
| checksum 不一致 | 不允许直接合并 |
| 业务确认 old1 或 old2 优先 | 记录覆盖规则并保留被覆盖源只读 fallback |
| 业务不能接受覆盖 | 改用来源前缀 bucket，例如 `old1-BUCKET`、`old2-BUCKET` |

生产执行时，只有在重复 key 已清零或有明确处置表后，才允许执行：

```bash
mc mirror --overwrite --retry --summary old1/BUCKET sw/BUCKET
mc mirror --overwrite --retry --summary old2/BUCKET sw/BUCKET
```

## 7. 对账校验

生成目标清单：

```bash
mc ls --recursive --json sw/TARGET_BUCKET \
  | jq -r 'select(.key != null) | [.key, .size] | @tsv' \
  | LC_ALL=C sort > sw.TARGET_BUCKET.manifest
```

对账：

```bash
diff -u old1.SOURCE_BUCKET.manifest sw.TARGET_BUCKET.manifest \
  > diff.SOURCE_BUCKET.txt
```

通过标准：

```text
diff 文件为空
```

## 8. Checksum 校验

不要完全依赖 ETag。大文件 multipart、压缩、加密、不同实现之间，ETag 不一定等于文件 MD5。

抽样建议：

```text
每个 bucket 随机抽样
所有大文件
所有中文、空格、特殊字符路径
热点文件
覆盖写对象
```

校验模板：

```bash
while IFS= read -r key; do
  mc cp "old1/SOURCE_BUCKET/$key" /tmp/migrate-check-old >/dev/null
  mc cp "sw/TARGET_BUCKET/$key" /tmp/migrate-check-new >/dev/null

  old_sha=$(sha256sum /tmp/migrate-check-old | awk '{print $1}')
  new_sha=$(sha256sum /tmp/migrate-check-new | awk '{print $1}')

  if [ "$old_sha" != "$new_sha" ]; then
    echo "FAIL $key old=$old_sha new=$new_sha"
  fi
done < sample.keys
```

通过标准：

```text
没有 FAIL
```

## 9. 增量、覆盖、删除策略

本次测试结论：

```text
mc mirror 默认不会删除目标端额外对象
带 --remove 后会删除目标端源端已不存在的对象
```

生产建议：

```text
常规迁移批次不用 --remove
最终停写窗口内，如果要求目标严格等同源端，再单独执行 --remove
执行 --remove 前必须确认源端清单正确
```

最终同步模板：

```bash
mc mirror \
  --overwrite \
  --remove \
  --retry \
  --summary \
  old1/SOURCE_BUCKET \
  sw/TARGET_BUCKET
```

## 10. 灰度切读

推荐灰度顺序：

```text
内部测试用户
低风险 bucket
冷数据 prefix
普通用户小流量
热点读文件
核心业务
```

读路由建议：

```text
storage_backend = seaweedfs -> 从 SeaweedFS 读
storage_backend = minio_old_x -> 从旧 MinIO 读
SeaweedFS 读失败 -> fallback 到旧 MinIO，并记录日志
```

fallback 日志至少包含：

```text
bucket
object key
用户或业务 id
错误码
源 backend
目标 backend
时间
```

## 11. 回滚策略

灰度期间必须满足：

```text
旧 MinIO 保持只读
业务读路由可切回旧 MinIO
SeaweedFS 失败不影响旧数据读取
迁移批次有报告和对象清单
```

遇到以下情况立即暂停切读：

```text
manifest diff 非空
checksum mismatch
SeaweedFS 写入或读取错误增加
fallback 数量异常
路径冲突未处理
Filer metadata store 异常
```

## 12. 下线旧 MinIO

不要在迁移后立即删除旧数据。

建议：

```text
旧 MinIO 只读保留 30 到 90 天
连续 7 到 14 天无 fallback 后进入下线评审
下线前再次确认备份、审计、业务验收记录
```

## 13. 本次测试暴露的生产化事项

1. SeaweedFS S3 Gateway 必须配置认证。
2. Volume Server `-max` 必须按规模估算，测试中 `-max=20` 不够。
3. `mc mirror --remove` 必须谨慎，只适合最终停写后的严格同步窗口。
4. 真实生产数据仍需扫描 `a/b` 与 `a/b/c` 路径冲突。
5. 生产 SeaweedFS 需要高可用 metadata store 和多副本策略。

## 14. 用户目录合并后的大目录风险

当前 MinIO 数据按以下方式分组：

```text
bucket/{userid}/<video-object>
```

如果有 10 个 MinIO，每个 MinIO 中同一个用户上传 1 万个视频，那么合并到同一个 SeaweedFS bucket 后会变成：

```text
bucket/{userid}/ 下约 10 万个对象
```

### 14.1 SeaweedFS 是否受操作系统目录文件数限制

SeaweedFS 的 Volume Server 不会把每个 object 按真实 Linux 文件路径保存为：

```text
/data/bucket/{userid}/video.mp4
```

对象数据会进入 SeaweedFS volume 文件，目录和文件名由 Filer metadata store 管理。因此，合并后 `bucket/{userid}` 下有 10 万个对象，不会直接触发 Linux 单目录文件数限制。

### 14.2 仍然存在的风险

风险会转移到 Filer/list 层：

```text
一次性列出 bucket/{userid}/ 下全部对象
Filer HTTP 目录列表
S3 ListObjectsV2 大 prefix 分页
FUSE 挂载后对该目录执行 ls
业务后台全量扫描用户目录
```

这些操作可能出现慢查询、高内存占用、接口超时或分页过深问题。

生产约束：

```text
业务读取单个文件必须使用完整 object key GET。
业务不得依赖一次性列出 bucket/{userid}/ 下全部对象。
后台任务必须分页扫描，不能全目录一次性拉取。
如果业务需要展示用户文件列表，应优先走业务数据库分页，而不是直接 list 对象存储目录。
```

### 14.3 新写入路径建议

为了降低长期大 prefix 风险，新写入建议逐步改为分片路径：

```text
bucket/{userid}/{yyyy}/{mm}/{video_id}
bucket/{userid}/{hash_prefix}/{video_id}
bucket/{userid}/{video_id_prefix}/{video_id}
```

历史数据可以保持原路径，只换 host；新数据逐步通过数据库记录真实 object key。

## 15. 大数据量内网迁移效率测试计划

### 15.1 当前环境变化

4070 的数据盘已被拔掉，不再适合作为 SeaweedFS 测试目标机。

已检查候选机器：

| 服务器 | 结果 |
| --- | --- |
| A3802 `172.16.100.234` | 当前 SSH 22 端口拒绝连接，暂不可用 |
| B580 `172.16.100.239` | 仅根分区约 466G，可用约 406G；无 1T+ 数据盘，且已有 RustFS 占用 9000 |
| dba380 `172.16.101.27` | 仅约 98G 根分区，无 1T+ 数据盘 |
| 890 `172.16.101.33` | 仅约 98G 根分区，无 1T+ 数据盘 |
| A770 `172.16.100.56` | 之前检查仅约 466G 根分区，无 1T+ 数据盘 |
| A380 `172.16.100.132` | 有 4 块约 15T 数据盘，但它是本轮源端 |

当前结论：

```text
已连通的非源端候选机器中，暂未找到独立 1T+ 数据盘的 SeaweedFS 目标机。
```

推荐优先级：

```text
1. 恢复 A3802 SSH，如果它有类似 A380 的数据盘，优先作为 SeaweedFS 目标机。
2. 恢复或重新挂载 4070 的 1T+ 数据盘后继续作为目标机。
3. 提供新的 1T+ 数据盘服务器作为目标机。
4. 不建议用 B580 承载 400-600G 测速，因为可用空间不足且缺少余量。
5. 不建议用 A380 同机做目标测速，因为无法代表内网跨机迁移效率。
```

### 15.2 A380 源端现状

A380 有 4 块约 15T XFS 数据盘：

```text
/data/data1
/data/data2
/data/data3
/data/data4
```

挂载层显示 `/data/data1` 已用约 458G，符合 400-600G 测试数据量级。

A380 上存在历史 MinIO 容器：

```text
minio_local
```

状态：

```text
Exited
```

它挂载：

```text
/data/data1 -> /data-1
/data/data2 -> /data-2
/data/data3 -> /data-3
/data/data4 -> /data-4
```

注意：该历史 MinIO 曾尝试向 `172.16.100.217:9000` 做 cold tier transition。启动前必须先确认 lifecycle / tier 配置，避免测试过程中继续向已不适合作为目标的 4070 写入或报错。

### 15.2.1 A380 原 MinIO 恢复记录（2026-05-29）

现象：

```text
Docker 容器 minio_local 监听 9000/9090，但健康接口返回 X-Minio-Server-Status: offline。
日志报错：Unable to initialize backend: Storage resources are insufficient for the read operation .minio.sys/pool.bin
```

恢复前备份：

```text
/data/minio-recovery-backups/20260529-144927
```

备份内容包括：

```text
minio_local 容器 inspect
minio_local 日志 tail
/etc/default/minio
df/mount/top-level 清单
/data/data1..4/.minio.sys 压缩包和 sha256
```

根因判断：

```text
旧 Docker 容器使用 MinIO RELEASE.2022-11-08T05-27-07Z。
.minio.sys/pool.bin 已被新格式写入，旧镜像读取时报 Unknown xl header version 3。
A380 主机上的 /usr/local/bin/minio 为 RELEASE.2025-09-07T16-13-09Z，可以正常读取当前元数据。
```

当前恢复方式：

```text
systemd 服务：minio-local.service
二进制：/usr/local/bin/minio
配置：/etc/default/minio-host-recovery
数据：MINIO_VOLUMES="/data/data{1...4}"
API：http://172.16.100.132:9000
Console：http://172.16.100.132:9090
```

原 Docker 容器状态：

```text
minio_local 已停止，保留用于回溯，不再作为当前服务入口。
minio_migration_test_old1 仍是隔离测试容器，端口 10100/10190。
```

验证结果：

```text
GET /minio/health/ready -> HTTP 200
Console / -> HTTP 200
S3 ListBuckets -> sucaiwang,testbucket
S3 ListObjectsV2 sucaiwang -> 可列出对象 key
```

注意：

```text
/usr/local/bin/mc 当前会 Segmentation fault，不要用它做迁移验证。
迁移工具需要在目标机安装可用版本的 mc，或改用 rclone/aws-cli/自研签名校验脚本。
```

### 15.3 单台 MinIO 大数据迁移测速流程

目标：

```text
只测试 A380 单台 MinIO -> 新 SeaweedFS 目标机。
验证 400-600G 数据在内网环境下的迁移效率、稳定性和校验成本。
```

推荐数据路径：

```text
A380 minio_local -> mc mirror -> 新 SeaweedFS S3 Gateway
```

迁移执行机建议放在 SeaweedFS 目标机上，使数据路径为：

```text
A380 -> 目标机
```

这样测到的是内网跨机迁移吞吐，而不是本机回环或外网跳板速度。

步骤：

```text
1. 选定 1T+ 目标机。
2. 在目标机数据盘上部署单机 SeaweedFS 测试环境。
3. 确认 A380 minio_local 启动方式和 lifecycle/tier 配置。
4. 只选择一个真实大 bucket 或一个用户 prefix 做迁移。
5. 迁移前生成 source manifest。
6. 执行 mc mirror，记录开始时间、结束时间、总字节、平均吞吐。
7. 迁移后生成 target manifest。
8. 做 key + size 全量 diff。
9. 抽样 sha256 校验大文件、热点文件、特殊路径。
10. 记录源端和目标端 CPU、网络、磁盘 IO。
```

测速指标：

```text
源 bucket / prefix
对象数
总大小
最大对象
迁移耗时
平均吞吐
峰值网络
源端磁盘读
目标端磁盘写
mc mirror 重试次数
失败对象数
manifest diff 数量
checksum 失败数
```

通过标准：

```text
mc mirror 退出码为 0
manifest diff 为空
checksum 样本无失败
迁移期间源 MinIO 和目标 SeaweedFS 无持续错误日志
吞吐结果可复现，至少跑两轮或按 prefix 跑两个批次
```
