# MinIO 到 SeaweedFS 迁移测试方案

生成日期：2026-05-26

## 1. 项目背景

当前项目专注于 MinIO 迁移。历史文档中的服务器转码测试用途不纳入本方案，仅保留服务器可被分配为测试角色这一事实。

参考建议的核心前提是：业务未使用复杂 S3 高级能力，MinIO 主要承担文件上传、下载、删除服务。因此迁移测试优先验证“文件服务迁移”是否可控，而不是验证完整 S3 能力迁移。

## 2. 测试目标

本次测试要回答以下问题：

1. 旧 MinIO 中的对象能否稳定迁移到 SeaweedFS。
2. 使用 `mc mirror` 通过 SeaweedFS S3 Gateway 迁移是否足够可靠。
3. 迁移前是否能发现 SeaweedFS 与 S3 路径语义差异造成的 key 冲突。
4. 全量 key、size 对账和抽样 checksum 校验是否能形成生产可复用流程。
5. 新写入切 SeaweedFS、旧 MinIO 停写或只读、灰度切读、旧 MinIO 保留的生产流程是否可执行。
6. 迁移过程中需要记录哪些数据，才能完善最终生产迁移 runbook。

## 3. 默认假设

1. 至少使用 3 台服务器：
   - `MINIO_OLD_1`：模拟第一套待迁移 MinIO。
   - `MINIO_OLD_2`：模拟第二套待迁移 MinIO。
   - `SEAWEEDFS_NEW`：模拟新的 SeaweedFS。
2. 迁移测试阶段可以临时启用 SeaweedFS S3 Gateway。
3. 业务最终可以走 SeaweedFS Filer HTTP，也可以继续通过内部文件服务封装访问，测试阶段先用 S3 Gateway 降低迁移工具复杂度。
4. 旧 MinIO 不迁移 versioning、object lock、retention、legal hold、replication、notification、复杂 ACL、复杂 bucket policy。
5. 测试方案不保存服务器密码、access key、secret key。敏感信息只放在本机私有 runbook 或临时 shell 环境变量中。

## 4. 推荐测试架构

```text
                 +----------------------+
                 |  migration runner    |
                 |  mc / jq / sha256sum |
                 +----------+-----------+
                            |
              +-------------+--------------+
              |                            |
              v                            v
   +--------------------+       +--------------------+
   | MINIO_OLD_1        |       | MINIO_OLD_2        |
   | S3 endpoint old1   |       | S3 endpoint old2   |
   +----------+---------+       +----------+---------+
              \                            /
               \                          /
                v                        v
             +------------------------------+
             | SEAWEEDFS_NEW                |
             | Master + Volume + Filer      |
             | S3 Gateway for migration     |
             +------------------------------+
```

测试阶段 `SEAWEEDFS_NEW` 可以在一台服务器上运行 Master、Volume、Filer、S3 Gateway。生产阶段不建议照搬单机形态，应至少规划：

```text
Master x 3
Volume Server x N
Filer x 2
S3 Gateway x 1~2，仅迁移期或兼容期使用
Filer Metadata Store 使用高可用 MySQL / PostgreSQL / Redis / Cassandra 等
```

## 5. 方案选择

### 5.1 推荐方案：S3 Gateway + mc mirror

迁移链路：

```text
旧 MinIO S3 API -> mc mirror -> SeaweedFS S3 Gateway -> SeaweedFS Filer/Volume
```

优点：

1. 迁移工具成熟，不需要先自研下载再上传脚本。
2. 能复用 `mc mirror --overwrite --retry --summary`。
3. 方便做 bucket 级、prefix 级分批迁移。
4. 业务最终不一定继续使用 S3 Gateway，迁移期使用即可。

缺点：

1. 需要确认 SeaweedFS S3 Gateway 对当前数据形态兼容。
2. 仍然需要单独做 key 冲突、manifest、checksum 校验。

### 5.2 备选方案：MinIO 下载 + Filer HTTP 上传

迁移链路：

```text
旧 MinIO -> 自研迁移脚本 -> SeaweedFS Filer HTTP
```

优点：

1. 更贴近最终文件服务模式。
2. 可以完全绕开 S3 Gateway。

缺点：

1. 需要自研重试、断点、失败记录、并发控制、校验逻辑。
2. 迁移工具复杂度更高，第一轮测试不建议直接采用。

### 5.3 本轮结论

第一轮迁移测试采用 5.1：

```text
迁移使用 SeaweedFS S3 Gateway + mc mirror
业务兼容性额外验证 Filer HTTP 上传、下载、列目录
```

## 6. 测试数据设计

每个旧 MinIO 至少准备 2 个 bucket：

```text
legacy-a
legacy-b
```

每个 bucket 准备以下对象类型：

| 类型 | 示例 key | 目的 |
| --- | --- | --- |
| 普通小文件 | `normal/000001.txt` | 基础迁移 |
| 多级目录 | `tenant/1001/2026/05/file.txt` | prefix 保持 |
| 中文路径 | `中文/合同/样例.txt` | 编码验证 |
| 空格路径 | `space dir/file name.txt` | URL 与 shell 转义验证 |
| 特殊字符 | `symbols/a+b&c=test.txt` | key 兼容性验证 |
| 大文件 | `large/1g.bin` | multipart / 大对象读取验证 |
| 零字节文件 | `empty/zero.txt` | 边界对象验证 |
| 覆盖写文件 | `overwrite/same-key.txt` | `--overwrite` 验证 |
| 删除场景 | `delete/to-be-deleted.txt` | 最终同步与删除策略验证 |
| 路径冲突 | `conflict/a` 与 `conflict/a/b.txt` | SeaweedFS 路径语义差异验证 |

路径冲突对象只用于验证扫描能力。发现冲突后不要直接迁移进入正式目标 bucket，应先形成冲突处置清单。

## 7. 环境准备

### 7.1 工具准备

迁移执行机安装：

```bash
mc --version
jq --version
sha256sum --version || shasum -a 256 --version
```

如果执行机是 macOS，`sha256sum` 可能不存在，可安装 GNU coreutils 或使用：

```bash
shasum -a 256 file
```

### 7.2 Alias 配置

使用环境变量保存敏感信息：

```bash
export OLD1_ENDPOINT="http://MINIO_OLD_1:9000"
export OLD2_ENDPOINT="http://MINIO_OLD_2:9000"
export SW_ENDPOINT="http://SEAWEEDFS_NEW:8333"

read -rsp "OLD1 access key: " OLD1_AK; echo
read -rsp "OLD1 secret key: " OLD1_SK; echo
read -rsp "OLD2 access key: " OLD2_AK; echo
read -rsp "OLD2 secret key: " OLD2_SK; echo
read -rsp "SeaweedFS access key: " SW_AK; echo
read -rsp "SeaweedFS secret key: " SW_SK; echo
```

配置 `mc`：

```bash
mc alias set old1 "$OLD1_ENDPOINT" "$OLD1_AK" "$OLD1_SK" --api S3v4
mc alias set old2 "$OLD2_ENDPOINT" "$OLD2_AK" "$OLD2_SK" --api S3v4
mc alias set sw   "$SW_ENDPOINT"   "$SW_AK"   "$SW_SK"   --api S3v4
```

连通性验证：

```bash
mc ls old1
mc ls old2
mc ls sw
```

## 8. 测试阶段

### 阶段 0：基线盘点

目标：确认旧 MinIO 当前数据形态，输出迁移前基线。

命令模板：

```bash
mkdir -p reports/manifests reports/conflicts reports/logs reports/checksum

for SRC in old1 old2; do
  mc ls "$SRC"
  for BUCKET in legacy-a legacy-b; do
    mc ls --recursive --json "$SRC/$BUCKET" \
      | jq -r '[.key, .size] | @tsv' \
      | LC_ALL=C sort > "reports/manifests/$SRC.$BUCKET.manifest"
  done
done
```

产物：

```text
reports/manifests/old1.legacy-a.manifest
reports/manifests/old1.legacy-b.manifest
reports/manifests/old2.legacy-a.manifest
reports/manifests/old2.legacy-b.manifest
```

通过标准：

1. 每个 bucket 均可列出对象。
2. manifest 中 key 与 size 格式稳定。
3. 对象总数、总大小可统计。

统计命令：

```bash
for FILE in reports/manifests/*.manifest; do
  count=$(wc -l < "$FILE" | tr -d ' ')
  bytes=$(awk -F '\t' '{sum += $2} END {print sum + 0}' "$FILE")
  echo "$FILE objects=$count bytes=$bytes"
done
```

### 阶段 1：SeaweedFS 兼容性冒烟

目标：确认新 SeaweedFS 可通过 S3 Gateway 写入、读取、删除，也可通过 Filer HTTP 做基础文件操作。

S3 Gateway 验证：

```bash
mc mb sw/smoke || true
printf 'hello seaweedfs\n' > /tmp/sw-smoke.txt
mc cp /tmp/sw-smoke.txt sw/smoke/sw-smoke.txt
mc cat sw/smoke/sw-smoke.txt
mc stat sw/smoke/sw-smoke.txt
mc rm sw/smoke/sw-smoke.txt
```

Filer HTTP 验证：

```bash
export FILER_ENDPOINT="http://SEAWEEDFS_NEW:8888"
printf 'hello filer\n' > /tmp/filer-smoke.txt
curl -f -F "file=@/tmp/filer-smoke.txt" "$FILER_ENDPOINT/smoke/"
curl -f "$FILER_ENDPOINT/smoke/filer-smoke.txt"
curl -f -H "Accept: application/json" "$FILER_ENDPOINT/smoke/?pretty=y"
```

通过标准：

1. S3 Gateway 可 `mb/cp/cat/stat/rm`。
2. Filer HTTP 可上传、读取、列目录。
3. SeaweedFS 服务日志无明显错误。

### 阶段 2：key 冲突扫描

目标：发现 S3 允许但 SeaweedFS 不允许的“同一路径同时是文件和目录”问题，例如：

```text
a/b
a/b/c
```

扫描命令：

```bash
for SRC in old1 old2; do
  for BUCKET in legacy-a legacy-b; do
    cut -f1 "reports/manifests/$SRC.$BUCKET.manifest" \
      | LC_ALL=C sort > "reports/conflicts/$SRC.$BUCKET.keys.sorted"

    awk '
      NR > 1 && index($0, prev "/") == 1 {
        print "CONFLICT\t" prev "\t" $0
      }
      { prev=$0 }
    ' "reports/conflicts/$SRC.$BUCKET.keys.sorted" \
      > "reports/conflicts/$SRC.$BUCKET.key_conflicts.txt"
  done
done
```

通过标准：

1. 冲突文件为空：可进入迁移。
2. 冲突文件非空：先确认处置策略，不直接进入正式迁移。

冲突处置策略：

| 策略 | 适用场景 | 说明 |
| --- | --- | --- |
| 重命名文件型 key | 冲突数量很少 | 例如 `a/b` 改为 `a/b.__file__` |
| 调整目录型 key | 业务可接受路径变化 | 例如 `a/b/c` 改到其他 prefix |
| 业务映射表兼容 | key 已被业务持久引用 | 数据层迁移时记录 old_key -> new_key |
| 保留旧 MinIO 读取 | 极少数历史冷数据 | 不迁入 SeaweedFS，读失败 fallback |

### 阶段 3：首次全量迁移

目标：验证 `mc mirror` 可将两个旧 MinIO 的 bucket 迁入 SeaweedFS。

目标 bucket 命名建议保留来源前缀，避免两个旧 MinIO 存在同名 bucket、同名 key 时互相覆盖：

```text
old1 legacy-a -> sw/old1-legacy-a
old1 legacy-b -> sw/old1-legacy-b
old2 legacy-a -> sw/old2-legacy-a
old2 legacy-b -> sw/old2-legacy-b
```

迁移命令：

```bash
for PAIR in \
  "old1 legacy-a old1-legacy-a" \
  "old1 legacy-b old1-legacy-b" \
  "old2 legacy-a old2-legacy-a" \
  "old2 legacy-b old2-legacy-b"
do
  set -- $PAIR
  SRC="$1"
  SRC_BUCKET="$2"
  DST_BUCKET="$3"

  mc mb "sw/$DST_BUCKET" || true

  mc mirror \
    --overwrite \
    --retry \
    --summary \
    --max-workers 16 \
    "$SRC/$SRC_BUCKET" \
    "sw/$DST_BUCKET" \
    2>&1 | tee "reports/logs/mirror.$SRC.$SRC_BUCKET.log"
done
```

通过标准：

1. `mc mirror` 退出码为 0。
2. 日志中没有未处理失败对象。
3. SeaweedFS 磁盘、CPU、内存、网络无异常瓶颈。

如果旧 MinIO 或新 SeaweedFS 压力过高，下一轮调整：

```text
--max-workers 降低到 4 或 8
--limit-upload 设置迁移带宽上限
按 bucket / prefix 拆小批次
```

### 阶段 4：全量 manifest 对账

目标：确认迁移后目标端 key 与 size 一致。

生成目标 manifest：

```bash
for DST_BUCKET in old1-legacy-a old1-legacy-b old2-legacy-a old2-legacy-b; do
  mc ls --recursive --json "sw/$DST_BUCKET" \
    | jq -r '[.key, .size] | @tsv' \
    | LC_ALL=C sort > "reports/manifests/sw.$DST_BUCKET.manifest"
done
```

对账：

```bash
diff -u reports/manifests/old1.legacy-a.manifest reports/manifests/sw.old1-legacy-a.manifest \
  > reports/manifests/diff.old1.legacy-a.txt || true

diff -u reports/manifests/old1.legacy-b.manifest reports/manifests/sw.old1-legacy-b.manifest \
  > reports/manifests/diff.old1.legacy-b.txt || true

diff -u reports/manifests/old2.legacy-a.manifest reports/manifests/sw.old2-legacy-a.manifest \
  > reports/manifests/diff.old2.legacy-a.txt || true

diff -u reports/manifests/old2.legacy-b.manifest reports/manifests/sw.old2-legacy-b.manifest \
  > reports/manifests/diff.old2.legacy-b.txt || true
```

通过标准：

```bash
for DIFF in reports/manifests/diff.*.txt; do
  if [ -s "$DIFF" ]; then
    echo "FAILED non-empty diff: $DIFF"
  else
    echo "PASS empty diff: $DIFF"
  fi
done
```

所有 diff 必须为空。

### 阶段 5：checksum 校验

目标：验证内容一致性，不依赖 ETag。

抽样策略：

1. 每个源 bucket 随机抽样 1000 个对象。
2. 所有大文件必须校验。
3. 所有中文、空格、特殊字符路径必须校验。
4. 覆盖写和删除相关对象必须校验最终状态。

生成样本：

```bash
for SRC in old1 old2; do
  for BUCKET in legacy-a legacy-b; do
    MANIFEST="reports/manifests/$SRC.$BUCKET.manifest"
    SAMPLE="reports/checksum/$SRC.$BUCKET.sample.keys"

    shuf -n 1000 "$MANIFEST" | cut -f1 > "$SAMPLE"
    grep -E 'large/|中文/|space dir/|symbols/|overwrite/' "$MANIFEST" | cut -f1 >> "$SAMPLE"
    LC_ALL=C sort -u "$SAMPLE" -o "$SAMPLE"
  done
done
```

校验函数：

```bash
checksum_one_pair() {
  src_alias="$1"
  src_bucket="$2"
  dst_bucket="$3"
  sample_file="$4"
  result_file="$5"

  mkdir -p /tmp/migrate-check/old /tmp/migrate-check/new
  : > "$result_file"

  while IFS= read -r key; do
    old_file="/tmp/migrate-check/old/object"
    new_file="/tmp/migrate-check/new/object"

    mc cp "$src_alias/$src_bucket/$key" "$old_file" >/dev/null
    mc cp "sw/$dst_bucket/$key" "$new_file" >/dev/null

    old_sha=$(sha256sum "$old_file" | awk '{print $1}')
    new_sha=$(sha256sum "$new_file" | awk '{print $1}')

    if [ "$old_sha" = "$new_sha" ]; then
      echo "PASS	$key	$old_sha" >> "$result_file"
    else
      echo "FAIL	$key	old=$old_sha	new=$new_sha" >> "$result_file"
    fi
  done < "$sample_file"
}
```

执行：

```bash
checksum_one_pair old1 legacy-a old1-legacy-a \
  reports/checksum/old1.legacy-a.sample.keys \
  reports/checksum/old1.legacy-a.sha256.tsv

checksum_one_pair old1 legacy-b old1-legacy-b \
  reports/checksum/old1.legacy-b.sample.keys \
  reports/checksum/old1.legacy-b.sha256.tsv

checksum_one_pair old2 legacy-a old2-legacy-a \
  reports/checksum/old2.legacy-a.sample.keys \
  reports/checksum/old2.legacy-a.sha256.tsv

checksum_one_pair old2 legacy-b old2-legacy-b \
  reports/checksum/old2.legacy-b.sample.keys \
  reports/checksum/old2.legacy-b.sha256.tsv
```

通过标准：

```bash
grep -R '^FAIL' reports/checksum/*.sha256.tsv
```

没有输出才算通过。

### 阶段 6：增量与停写窗口测试

目标：模拟生产中“迁移时旧 MinIO 仍有变化”和“最终短暂停写”的流程。

测试步骤：

1. 首次全量迁移完成后，在 `old1/legacy-a` 写入新对象、覆盖已有对象、删除测试对象。
2. 使用 `mc mirror --watch --overwrite --retry` 跑一轮持续同步。
3. 停止业务写入模拟，即不再对旧 MinIO 做 PUT / DELETE。
4. 终止 `--watch`。
5. 执行最终一次 `mc mirror --overwrite --retry --summary`。
6. 重新生成 manifest 与 checksum 样本。
7. 确认最终一致。

持续同步命令：

```bash
mc mirror \
  --watch \
  --overwrite \
  --retry \
  --summary \
  old1/legacy-a \
  sw/old1-legacy-a \
  2>&1 | tee reports/logs/watch.old1.legacy-a.log
```

最终同步命令：

```bash
mc mirror \
  --overwrite \
  --retry \
  --summary \
  old1/legacy-a \
  sw/old1-legacy-a \
  2>&1 | tee reports/logs/final.old1.legacy-a.log
```

删除策略说明：

1. 第一轮测试不要默认使用 `--remove`，避免误删目标端非源端对象。
2. 如果生产要求目标端严格等同源端，必须在旧 MinIO 已停写、源端清单确认无误后，单独测试 `--remove`。
3. 删除语义需要和业务删除逻辑一起确认，不能只由迁移命令决定。

通过标准：

1. 新增对象迁移成功。
2. 覆盖对象迁移为最终版本。
3. 删除对象的处置策略明确并被验证。
4. 停写后的最终 manifest 和 checksum 通过。

### 阶段 7：读写切换模拟

目标：验证生产切换策略。

推荐生产切换模型：

```text
新上传：直接写 SeaweedFS
旧文件：迁移前继续读旧 MinIO
已迁移文件：灰度切到 SeaweedFS
SeaweedFS 读失败：允许 fallback 到旧 MinIO，并记录日志
```

如果业务已有文件表，增加或复用存储后端字段：

```sql
ALTER TABLE file_info ADD COLUMN storage_backend VARCHAR(32) DEFAULT 'legacy';
ALTER TABLE file_info ADD COLUMN migrated_at DATETIME NULL;
```

示例状态：

```text
storage_backend = minio_old_1
storage_backend = minio_old_2
storage_backend = seaweedfs
```

灰度顺序：

1. 内部测试用户。
2. 低风险 bucket。
3. 冷数据 prefix。
4. 普通用户小流量。
5. 热点读文件。
6. 核心业务。

通过标准：

1. 切换到 SeaweedFS 后下载内容正确。
2. 读失败 fallback 到旧 MinIO 可用。
3. fallback 日志可按 bucket、key、用户、错误码聚合。
4. 可一键将灰度对象切回旧 MinIO。

### 阶段 8：故障与回滚演练

目标：确认生产迁移遇到问题时不会被迫硬切。

必须演练：

| 场景 | 预期处理 |
| --- | --- |
| `mc mirror` 中断 | 重新执行同一命令可继续同步 |
| 单个对象迁移失败 | 失败 key 进入清单，修复后重跑 |
| manifest diff 非空 | 不进入切读，先定位缺失或大小不一致对象 |
| checksum mismatch | 不进入切读，重新迁移该 key 并复核 |
| SeaweedFS S3 Gateway 不稳定 | 暂停迁移，不影响旧 MinIO 读 |
| Filer metadata 异常 | 不切生产读，恢复元数据后重验 |
| 灰度读失败上升 | 业务读路由切回旧 MinIO |
| 发现路径冲突 | 对冲突 key 单独决策，不批量迁入 |

回滚原则：

1. 旧 MinIO 在迁移完成后一段时间内保持只读保留。
2. 在生产确认期内，不删除旧 MinIO 数据。
3. 灰度阶段所有切换都要有反向操作。
4. SeaweedFS 迁移失败不影响旧数据继续服务。

## 9. 生产方案沉淀项

测试过程中必须记录以下数据，用于完善生产迁移方案：

| 类别 | 记录项 |
| --- | --- |
| 数据规模 | bucket 数、对象数、总大小、最大对象、平均对象大小 |
| key 风险 | 路径冲突数量、中文/空格/特殊字符 key 数量 |
| 性能 | 每 bucket 迁移耗时、平均吞吐、峰值吞吐 |
| 资源 | old MinIO CPU/内存/磁盘 IO/网络，SeaweedFS CPU/内存/磁盘 IO/网络 |
| 并发 | `--max-workers` 从 4、8、16、32 的效果 |
| 限速 | 是否需要 `--limit-upload` 或按时间窗口迁移 |
| 校验 | manifest diff 数、checksum mismatch 数 |
| 稳定性 | mirror 重试次数、失败 key 数、重跑成功率 |
| 切换 | 灰度批次、fallback 次数、读失败错误码 |
| 运维 | 日志位置、告警项、恢复步骤、旧 MinIO 保留周期 |

## 10. 生产迁移草案

测试通过后，生产迁移采用以下流程：

```text
1. 盘点旧 MinIO bucket、对象数、总大小、key 风险。
2. 搭建生产 SeaweedFS 集群，不使用单副本。
3. 配置 Filer Metadata Store 高可用和备份。
4. 新写入先切 SeaweedFS。
5. 旧 MinIO 停写或只读，只保留 GET / HEAD / LIST。
6. 按 bucket / prefix / 用户分批执行 mc mirror。
7. 每批做 key + size 全量对账。
8. 每批做大文件、热点文件、特殊路径、随机样本 checksum。
9. 灰度切读，保留旧 MinIO fallback。
10. 观察 30 到 90 天。
11. 连续 7 到 14 天无 fallback 后，再进入旧 MinIO 下线评审。
```

生产硬性底线：

1. 旧 MinIO 最终迁移前必须停写或只读。
2. SeaweedFS 不使用单副本承载生产数据。
3. Filer Metadata Store 必须有备份。
4. 不完全依赖 ETag 判断内容一致。
5. 旧 MinIO 不在切换后立即删除。
6. `a/b` 与 `a/b/c` 这类路径冲突必须迁移前扫描。
7. 每批迁移都有可审计报告。

## 11. 验收标准

测试通过需要同时满足：

1. 两个旧 MinIO 的所有测试 bucket 均成功迁入 SeaweedFS。
2. 所有测试 bucket 的 manifest diff 为空。
3. checksum 样本没有失败项。
4. 路径冲突扫描能正确发现构造的冲突样本。
5. 新增、覆盖、删除场景均有明确迁移行为和处理策略。
6. Filer HTTP 上传、读取、列目录通过。
7. 灰度读切换和 fallback 通过。
8. 至少完成一次迁移中断后重跑演练。
9. 形成生产迁移参数建议：批次大小、并发、限速、停写窗口、保留周期。

## 12. 测试输出物

测试结束后保留：

```text
reports/manifests/*.manifest
reports/manifests/diff.*.txt
reports/conflicts/*.key_conflicts.txt
reports/checksum/*.sample.keys
reports/checksum/*.sha256.tsv
reports/logs/*.log
```

最终整理一份生产迁移 runbook，至少包含：

1. 服务器角色映射。
2. SeaweedFS 生产拓扑。
3. bucket / prefix 批次表。
4. 停写和切写步骤。
5. 迁移命令。
6. 校验命令。
7. 灰度切读步骤。
8. fallback 和回滚步骤。
9. 旧 MinIO 保留和下线标准。

## 13. 参考依据

1. MinIO `mc mirror` 支持 S3-compatible host 到 S3-compatible host 的同步，支持 `--overwrite`、`--retry`、`--summary`、`--watch` 等参数：<https://min.io/docs/minio/linux/reference/minio-mc/mc-mirror.html>
2. SeaweedFS `weed s3` 是桥接 Amazon S3 API 到 SeaweedFS Filer 的无状态网关：<https://github-wiki-see.page/m/seaweedfs/seaweedfs/wiki/Amazon-S3-API>
3. SeaweedFS Filer HTTP API 支持上传、读取、HEAD 和 JSON 列目录：<https://github-wiki-see.page/m/seaweedfs/seaweedfs/wiki/Filer-Server-API>
4. SeaweedFS 与 AWS S3 的重要差异之一是：SeaweedFS 不支持同一路径同时既是文件又是目录。该限制属于 SeaweedFS S3/Filer 路径语义，需要在迁移前用本方案的 key 冲突扫描验证：<https://github-wiki-see.page/m/seaweedfs/seaweedfs/wiki/Amazon-S3-API>
