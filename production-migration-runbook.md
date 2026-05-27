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
