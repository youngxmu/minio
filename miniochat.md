可以，**在“不用版本控制、不依赖高级 S3 能力”的前提下，迁移方案可以明显简化**。

不过有一个前提要说清楚：MinIO 本质上还是 S3-compatible 对象存储。你说“没有使用到 S3”，我理解为你们业务没有用 S3 的高级能力，例如 versioning、bucket policy、object lock、replication、notification、复杂 ACL、presigned URL 等，只是把 MinIO 当成“上传文件、下载文件、删除文件”的文件服务来用。如果是这个情况，迁移会简单很多。

## 简化后的核心结论

你们现在可以从前面那种“完整对象存储迁移方案”简化成：

```text
新写入切到 SeaweedFS
旧 MinIO 改只读或停止写入
批量复制当前文件
做文件数量、大小、抽样 checksum 校验
读流量灰度切到 SeaweedFS
旧 MinIO 保留只读一段时间
确认无问题后退役
```

不再需要做这些复杂工作：

```text
不需要迁移 version_id
不需要 ListObjectVersions
不需要 old_version_id -> new_version_id 映射
不需要处理 delete marker
不需要处理 Object Lock / Retention / Legal Hold
不需要处理 Bucket Replication
不需要处理复杂 bucket policy / ACL / IAM
不需要长期维护复杂的对象级多版本路由
```

但仍然不能省：

```text
不能省迁移校验
不能省旧 MinIO 只读保留
不能省灰度切流
不能省 key 冲突检查
不能省新系统副本/备份设计
```

SeaweedFS 本身支持通过 Filer 直接用 HTTP 上传、读取、列目录；官方示例里可以用 HTTP POST 上传文件、HTTP GET 读取文件，并且 Filer 会负责把元数据和文件块写入后端 Volume Server。([GitHub][1]) 如果你们业务本来就是“文件服务模式”，不强依赖 S3 SDK，那么可以直接使用 SeaweedFS Filer HTTP 接口，而不一定让业务走 S3 Gateway。

---

# 一、推荐的最简架构

如果你们不需要 S3 语义，推荐这样：

```text
业务服务
  |
  | 上传 / 下载
  v
统一文件服务域名：file.example.com
  |
  v
LB / Nginx
  |
  v
SeaweedFS Filer x 2+
  |
  v
SeaweedFS Master x 3
SeaweedFS Volume Server x N
Filer Metadata Store
```

业务以后只访问：

```text
https://file.example.com/path/to/file
```

后面由 SeaweedFS Filer 负责文件存取。

SeaweedFS 的设计目标之一是处理大量文件，并且文件访问路径是通过 volume id 定位，官方 README 中强调其小文件访问通常是 O(1) 磁盘读取；Filer 则负责目录和元数据，元数据后端可以选择 MySQL、Postgres、Redis、Cassandra、LevelDB、RocksDB 等。([GitHub][2])

---

# 二、迁移工具可以怎么选

虽然业务不一定需要 S3，但**迁移时仍然可以临时启用 SeaweedFS S3 Gateway**，这样迁移工具最简单。

SeaweedFS 的 `weed s3` 是一个无状态网关，用来把 Amazon S3 API 桥接到 SeaweedFS Filer；官方文档也说明可以启动多个 S3 实例做横向扩展。([GitHub][3])

所以推荐：

```text
业务访问：
  可以走 SeaweedFS Filer HTTP

迁移任务：
  临时走 SeaweedFS S3 Gateway
  用 mc mirror 从 MinIO 复制到 SeaweedFS
```

这样不用自己写大量下载再上传脚本。

---

# 三、最简迁移流程

## 方案 A：可以接受短暂停写，最简单、最安全

这是我最推荐的方案。

### 步骤 1：搭建 SeaweedFS

至少建议：

```text
Master x 3
Volume Server x N
Filer x 2
S3 Gateway x 1~2，迁移期间使用
Filer Metadata Store，建议 MySQL/Postgres/Redis/Cassandra 等高可用方案
```

Volume Server 不建议用 `replication=000`。至少用 2 副本，例如：

```text
001：同 rack 复制 1 份
010：同数据中心不同 rack 复制 1 份
```

如果你们只有一个机房，先用 `001`；如果有 rack 规划，用 `010` 更好。

---

### 步骤 2：所有新上传先切到 SeaweedFS

业务写入逻辑改成：

```text
新文件 -> SeaweedFS
旧文件 -> 仍然从旧 MinIO 读
```

如果你们有文件表，建议只加一个字段即可：

```sql
ALTER TABLE file_info ADD COLUMN storage_backend VARCHAR(32);
```

例如：

```text
storage_backend = minio_old_1
storage_backend = minio_old_2
storage_backend = seaweedfs
```

如果当前数据库里已经记录了文件属于哪台 MinIO，就更简单，不需要新增复杂对象位置表。

---

### 步骤 3：旧 MinIO 停写或只读

这是关键。

因为你们没有版本控制，所以如果迁移过程中旧 MinIO 还在被覆盖写入，容易出现：

```text
迁移任务复制了旧版本
业务随后覆盖了新版本
最后切流后 SeaweedFS 里不是最新文件
```

所以最简单安全的方式是：

```text
1. 新写入全部切 SeaweedFS
2. 旧 MinIO 禁止 PUT / DELETE
3. 旧 MinIO 只保留 GET / HEAD / LIST
4. 开始批量迁移历史文件
```

---

### 步骤 4：用 mc mirror 批量迁移

配置旧 MinIO：

```bash
mc alias set old1 https://minio-old1.example.com OLD1_AK OLD1_SK --api S3v4
mc alias set old2 https://minio-old2.example.com OLD2_AK OLD2_SK --api S3v4
```

配置 SeaweedFS S3 Gateway：

```bash
mc alias set sw https://seaweedfs-s3.example.com SW_AK SW_SK --api S3v4
```

迁移 bucket：

```bash
mc mb sw/bucket-a || true

mc mirror \
  --overwrite \
  --retry \
  --summary \
  old1/bucket-a \
  sw/bucket-a
```

MinIO 官方文档说明，`mc mirror` 可以同步一个 S3-compatible host 的 bucket 到另一个 S3-compatible host；`--overwrite` 会在源对象变化时覆盖目标端对象；`--retry` 会对出错对象重试；`--summary` 会输出同步摘要。([MinIO AIStor Documentation][4])

如果你们已经把旧 MinIO 只读了，一般不需要 `--watch`。

如果短时间内不能停写，可以临时用：

```bash
mc mirror \
  --watch \
  --overwrite \
  --retry \
  --summary \
  old1/bucket-a \
  sw/bucket-a
```

但最终切流前，仍然建议做一次短暂停写和最终校验。`--watch` 会持续同步源到目标，目标端也可以存在源端没有的额外对象。([MinIO AIStor Documentation][4])

---

### 步骤 5：校验

#### 1. 校验数量和大小

```bash
mc ls --recursive --json old1/bucket-a \
  | jq -r '[.key, .size] | @tsv' \
  | LC_ALL=C sort > old1.bucket-a.manifest

mc ls --recursive --json sw/bucket-a \
  | jq -r '[.key, .size] | @tsv' \
  | LC_ALL=C sort > sw.bucket-a.manifest

diff -u old1.bucket-a.manifest sw.bucket-a.manifest > bucket-a.diff
```

`bucket-a.diff` 为空，说明对象名和大小一致。

---

#### 2. 抽样 checksum 校验

随机抽样一些文件：

```bash
shuf -n 1000 old1.bucket-a.manifest | cut -f1 > sample.keys
```

对每个 key 下载旧文件和新文件，计算 sha256：

```bash
while read key; do
  mkdir -p /tmp/migrate-check/old /tmp/migrate-check/new

  mc cp "old1/bucket-a/$key" "/tmp/migrate-check/old/file" >/dev/null
  mc cp "sw/bucket-a/$key"   "/tmp/migrate-check/new/file" >/dev/null

  old_sha=$(sha256sum /tmp/migrate-check/old/file | awk '{print $1}')
  new_sha=$(sha256sum /tmp/migrate-check/new/file | awk '{print $1}')

  if [ "$old_sha" != "$new_sha" ]; then
    echo "checksum mismatch: $key"
  fi
done < sample.keys
```

不要完全依赖 ETag。大文件 multipart、压缩、加密、不同实现之间，ETag 不一定等于文件 MD5。

---

### 步骤 6：灰度切读

切读逻辑可以很简单：

```text
如果 storage_backend = seaweedfs：
  从 SeaweedFS 读

如果 storage_backend = minio_old_x：
  从旧 MinIO 读
```

迁移完成某个用户、某个 bucket 或某个 prefix 后，把数据库标记改掉：

```sql
UPDATE file_info
SET storage_backend = 'seaweedfs'
WHERE storage_backend = 'minio_old_1'
  AND bucket = 'bucket-a'
  AND migrated = 1;
```

更简单一点，如果你们是按用户分组，可以按用户切：

```sql
UPDATE user_storage
SET storage_backend = 'seaweedfs'
WHERE user_id IN (...);
```

但我更建议至少按 bucket 或 prefix 迁移，不要继续形成“一个用户固定一台存储”的长期模型。用户级迁移可以作为过渡，最终所有新数据都应该进入统一 SeaweedFS 集群。

---

### 步骤 7：旧 MinIO 只读保留

迁移完成后，不要立刻删旧数据。

建议：

```text
旧 MinIO 只读保留 30~90 天
业务读 SeaweedFS 失败时允许 fallback 到旧 MinIO
记录所有 fallback 日志
连续 7~14 天无 fallback 后，再考虑下线旧 MinIO
```

---

# 四、如果完全不用 S3 Gateway，能不能迁？

也可以，但迁移脚本要自己写。

流程是：

```text
从 MinIO 下载文件
通过 SeaweedFS Filer HTTP 上传
记录成功状态
校验大小和 checksum
```

SeaweedFS Filer 官方示例支持：

```bash
# 上传
curl -F "filename=@README.md" "http://localhost:8888/path/to/sources/"

# 读取
curl "http://localhost:8888/path/to/sources/README.md"

# 列目录
curl -H "Accept: application/json" "http://localhost:8888/path/to?pretty=y"
```

这些能力来自 Filer 的 HTTP 接口，Filer 写入时会将数据上传到 Volume Server，并把元数据和 chunk 信息写到 Filer Store。([GitHub][1])

但是我不建议一开始就完全绕开 S3 Gateway。原因是：

```text
1. 旧数据在 MinIO 里，用 mc mirror 拉取最成熟。
2. SeaweedFS S3 Gateway 可以只作为迁移入口，不一定给业务用。
3. 自研迁移器要处理重试、并发、失败记录、断点续传。
4. mc mirror 已经帮你处理了很多对象同步细节。
```

所以更实用的做法是：

```text
迁移用 S3 Gateway + mc mirror
业务最终用 Filer HTTP 或你们自己的文件服务封装
```

---

# 五、当前前提下，迁移清单可以删减成这样

## 不需要做的检查

```text
versioning 检查：可以省
delete marker 检查：可以省
Object Lock 检查：可以省
Retention / Legal Hold：可以省
Bucket Replication：可以省
Bucket Notification：如果没用，可以省
复杂 bucket policy：如果没用，可以省
ACL 映射：如果没用，可以省
历史版本读取兼容：可以省
```

## 仍然必须做的检查

```text
1. 文件名 / object key 是否有冲突
2. 文件总数是否一致
3. 文件总大小是否一致
4. 抽样 checksum 是否一致
5. 大文件能否正常读写
6. 中文文件名、空格、特殊字符路径是否正常
7. 删除逻辑是否一致
8. 业务下载 URL 是否兼容
9. SeaweedFS 副本策略是否正确
10. Filer 元数据是否有备份
```

特别注意 SeaweedFS 的路径语义。SeaweedFS 文档明确说，SeaweedFS 不支持同一路径同时既是文件又是目录，而 AWS S3 可以。也就是说，下面这种 key 组合在 S3/MinIO 中可以存在，但在 SeaweedFS 中会冲突：([GitHub][3])

```text
a/b
a/b/c
```

迁移前建议至少跑一次扫描：

```bash
mc ls --recursive --json old1/bucket-a \
  | jq -r '.key' \
  | LC_ALL=C sort > bucket-a.keys.sorted

awk '
  NR > 1 && index($0, prev "/") == 1 {
    print "CONFLICT\t" prev "\t" $0
  }
  { prev=$0 }
' bucket-a.keys.sorted > bucket-a.key_conflicts.txt
```

如果 `bucket-a.key_conflicts.txt` 不为空，需要单独处理这些冲突对象。

---

# 六、最推荐的简化版方案

结合你们现在的情况，我建议采用这个版本：

```text
阶段 1：建 SeaweedFS 集群
- Master x3
- Volume Server xN
- Filer x2
- S3 Gateway x1~2，仅迁移期使用
- Filer metadata store 做高可用

阶段 2：新写入切 SeaweedFS
- 新上传全部写 SeaweedFS
- 旧 MinIO 不再接新写入
- 旧文件仍按原逻辑读旧 MinIO

阶段 3：旧 MinIO 只读
- 禁止 PUT / DELETE
- 只允许 GET / HEAD / LIST
- 防止无版本场景下出现覆盖丢失

阶段 4：批量迁移
- 用 mc mirror oldX/bucket -> sw/bucket
- 按 bucket / prefix / 用户分批迁
- 控制并发，避免把旧机器打满

阶段 5：校验
- 全量 key + size 对账
- 抽样 sha256
- 重点校验大文件、热点文件、中文路径、特殊字符路径

阶段 6：灰度切读
- 先切内部用户
- 再切低风险 bucket
- 再切热点读
- 最后切核心业务

阶段 7：旧 MinIO 保留
- 只读保留 30~90 天
- 记录 fallback
- 无 fallback 后退役
```

---

# 七、最简命令模板

假设每台旧 MinIO 一个 alias：

```bash
mc alias set old1 https://minio-old1.example.com OLD1_AK OLD1_SK --api S3v4
mc alias set old2 https://minio-old2.example.com OLD2_AK OLD2_SK --api S3v4
mc alias set sw   https://seaweedfs-s3.example.com SW_AK SW_SK --api S3v4
```

迁移 bucket：

```bash
BUCKET=bucket-a

mc mb sw/$BUCKET || true

mc mirror \
  --overwrite \
  --retry \
  --summary \
  old1/$BUCKET \
  sw/$BUCKET
```

生成清单：

```bash
mc ls --recursive --json old1/$BUCKET \
  | jq -r '[.key, .size] | @tsv' \
  | LC_ALL=C sort > old1.$BUCKET.manifest

mc ls --recursive --json sw/$BUCKET \
  | jq -r '[.key, .size] | @tsv' \
  | LC_ALL=C sort > sw.$BUCKET.manifest
```

对账：

```bash
diff -u old1.$BUCKET.manifest sw.$BUCKET.manifest > $BUCKET.diff
```

如果 diff 为空，就可以进入抽样 checksum 和灰度切读。

---

# 八、进一步简化：是否还需要对象位置表？

不一定。

如果你们当前已经有类似下面的信息：

```text
用户 A -> minio-old1
用户 B -> minio-old2
文件 id -> bucket + object_key
```

那就不需要新建复杂对象位置表，只需要增加一个迁移状态字段即可。

例如：

```sql
ALTER TABLE file_info ADD COLUMN storage_backend VARCHAR(32) DEFAULT 'legacy';
ALTER TABLE file_info ADD COLUMN migrated_at DATETIME NULL;
```

或者如果你们是用户级存储映射：

```sql
ALTER TABLE user_storage ADD COLUMN backend VARCHAR(32);
```

迁移前：

```text
user_id=1001 backend=minio-old1
```

迁移后：

```text
user_id=1001 backend=seaweedfs
```

读文件时：

```text
根据 backend 决定从旧 MinIO 还是 SeaweedFS 读
```

这种方式已经足够，不需要前面提到的复杂 `object_location` 表。

---

# 九、我会保留的安全底线

即使迁移已经简化，我也建议保留这几个底线：

```text
1. 旧 MinIO 最终迁移前必须停写或只读
2. SeaweedFS 不要用单副本
3. Filer metadata store 必须备份
4. 迁移后旧 MinIO 不要马上删除
5. 至少做 key + size 全量对账
6. 至少做热点文件和大文件 checksum 抽样
7. 必须处理 a/b 与 a/b/c 这种路径冲突
```

最简安全方案一句话就是：

> **新文件直接写 SeaweedFS；旧 MinIO 停写后用 `mc mirror` 搬当前对象；按 key 和 size 全量对账，抽样校验内容；灰度切读；旧 MinIO 只读保留一段时间。**

在你们不使用版本控制和高级 S3 能力的前提下，这已经是相对简单、可控、风险较低的迁移路径。

[1]: https://raw.githubusercontent.com/wiki/seaweedfs/seaweedfs/Directories-and-Files.md "raw.githubusercontent.com"
[2]: https://github.com/seaweedfs/seaweedfs "GitHub - seaweedfs/seaweedfs: SeaweedFS is a distributed storage system for object storage (S3), file systems, and Iceberg tables, designed to handle billions of files with O(1) disk access and effortless horizontal scaling. · GitHub"
[3]: https://raw.githubusercontent.com/wiki/seaweedfs/seaweedfs/Amazon-S3-API.md "raw.githubusercontent.com"
[4]: https://docs.min.io/aistor/reference/cli/mc-mirror/ "mc mirror | MinIO AIStor Documentation"
