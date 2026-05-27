# MinIO 到 SeaweedFS 迁移测试执行记录

执行日期：2026-05-27

## 1. 服务器角色

| 角色 | 服务器 | 用途 | 测试端口 |
| --- | --- | --- | --- |
| old1 | A380 `172.16.100.132` | 隔离 MinIO 测试源 1 | S3 `10100`，Console `10190` |
| old2 | A770 `172.16.100.56` | 隔离 MinIO 测试源 2 | S3 `9100`，Console `9190` |
| target | 4070 `172.16.100.217` | SeaweedFS 测试目标 + 迁移执行机 | Master `9333`，Volume `8080`，Filer `8888`，S3 `8333` |

本次测试全部使用隔离容器和隔离目录，没有启动 A380 原有的 `minio_local` 历史容器。

## 2. 部署结果

### A380

容器：

```text
minio_migration_test_old1
```

状态：

```text
Up
0.0.0.0:10100->9000/tcp
0.0.0.0:10190->9090/tcp
```

### A770

容器：

```text
minio_migration_test_old2
```

状态：

```text
Up
0.0.0.0:9100->9000/tcp
0.0.0.0:9190->9090/tcp
```

### 4070

容器：

```text
seaweedfs_migration_master
seaweedfs_migration_volume
seaweedfs_migration_filer
seaweedfs_migration_s3
```

状态：

```text
全部 Up
```

测试目录：

```text
/data/data1/seaweedfs-test
```

## 3. 迁移测试数据

源端 bucket：

```text
old1/legacy-a
old1/legacy-b
old1/legacy-conflict
old2/legacy-a
old2/legacy-b
old2/legacy-conflict
```

迁移 bucket：

```text
old1/legacy-a -> sw/old1-legacy-a
old1/legacy-b -> sw/old1-legacy-b
old2/legacy-a -> sw/old2-legacy-a
old2/legacy-b -> sw/old2-legacy-b
```

覆盖的数据类型：

```text
普通小文件
多级 prefix
中文路径
空格路径
特殊字符路径
零字节文件
8 MiB 大文件
覆盖写对象
新增对象
删除对象
```

## 4. 关键发现

### 4.1 SeaweedFS S3 Gateway 需要显式认证配置

最初不配置 S3 credentials 时，`mc mirror` 写入失败：

```text
Signed request requires setting up SeaweedFS S3 authentication
```

处理方式：

```text
为 SeaweedFS S3 Gateway 增加 s3.json identities 配置，并重启 S3 Gateway。
```

生产建议：

```text
不要依赖 SeaweedFS S3 Gateway 默认认证行为。
迁移期也应显式配置 access key / secret key / actions。
```

### 4.2 Volume Server 的 `-max` 不能过小

最初使用：

```text
weed volume -max=20
```

迁移第二个 bucket 时失败，master 日志显示：

```text
No writable volumes and no free volumes left
Not enough data nodes found
```

原因：

```text
SeaweedFS 会为 collection 预分配多个 volume。
20 个 volume 很快被 auth-smoke 和第一个迁移 bucket 用完。
```

处理方式：

```text
清空 SeaweedFS 测试目标目录，将 volume server 改为 -max=200 后重启。
```

生产建议：

```text
生产部署需要按 bucket / collection 数量、对象规模、volumeSizeLimitMB 估算 volume 上限。
测试环境不要把 -max 设置过小。
```

### 4.3 测试 MinIO 未能构造真实路径冲突

尝试构造：

```text
conflict/a
conflict/a/b.txt
```

实际结果：

```text
old1/legacy-conflict objects=1
old2/legacy-conflict objects=1
实际 MinIO 测试容器没有保留两个冲突对象。
```

补充验证：

```text
使用 synthetic manifest 验证冲突扫描逻辑，成功发现：
CONFLICT a/b a/b/c
```

生产建议：

```text
真实旧 MinIO 迁移前仍必须扫描 a/b 与 a/b/c 类路径冲突。
本次测试只能证明扫描脚本逻辑可用，不能证明生产数据无冲突。
```

## 5. 验证结果

### 5.1 基础迁移

迁移结果：

```text
sw/old1-legacy-a objects=9 bytes=8388760
sw/old1-legacy-b objects=8 bytes=8388721
sw/old2-legacy-a objects=8 bytes=8388721
sw/old2-legacy-b objects=8 bytes=8388721
```

`old1-legacy-a` 为 9 个对象，是因为后续增量测试增加了 `incremental/new-object.txt`，并在删除测试后保留最终一致状态。

### 5.2 Manifest 对账

以下 diff 均为空：

```text
diff.old1.legacy-a.txt
diff.old1.legacy-b.txt
diff.old2.legacy-a.txt
diff.old2.legacy-b.txt
diff.after-add.txt
diff.after-remove.txt
```

### 5.3 Checksum

结果：

```text
NO_CHECKSUM_FAIL
```

所有样本 sha256 校验通过。

### 5.4 增量、覆盖、删除

新增对象：

```text
incremental/new-object.txt
```

覆盖对象：

```text
overwrite/same-key.txt
```

验证结果：

```text
AFTER_ADD_DIFF_EMPTY
```

删除策略验证：

```text
不带 --remove：TARGET_RETAINED_WITHOUT_REMOVE
带 --remove：TARGET_REMOVED_WITH_REMOVE
最终 diff：AFTER_REMOVE_DIFF_EMPTY
```

结论：

```text
mc mirror 默认不会删除目标端额外对象。
如果生产要求严格同步删除，需要在停写窗口中单独使用 --remove，并先完成源端清单确认。
```

### 5.5 Filer HTTP

Filer HTTP 上传、读取、列目录均通过。

读取结果：

```text
hello filer http 2026-05-27
```

列表接口返回了 `Entries[].FullPath`，不是简单的 `Entries[].Name`。

## 6. 测试产物

4070 上的报告目录：

```text
/tmp/minio-migration-test/reports
```

本地脚本：

```text
/Users/zhangyang/Documents/Codex/minio/run-migration-test.sh
```

报告包含：

```text
manifests
conflicts
checksum
logs
incremental
```

## 7. 当前结论

本轮 3 台服务器迁移测试通过：

```text
A380 测试 MinIO -> SeaweedFS：通过
A770 测试 MinIO -> SeaweedFS：通过
mc mirror 基础迁移：通过
manifest 全量 key + size 对账：通过
sha256 内容校验：通过
增量与覆盖：通过
删除策略：已验证
Filer HTTP：通过
```

可进入下一步：

```text
1. 将本轮脚本和结果提交到 GitHub 仓库。
2. 把测试命令沉淀为生产 runbook。
3. 选择是否对 A380 原 minio_local 历史数据做只读扫描。
4. 为生产 SeaweedFS 设计多节点拓扑、volume 上限、metadata store 和备份方案。
```

## 8. Host-only 访问路径补充测试

用户确认生产目标倾向于“只换 host，不改 bucket 和 object key 相对路径”。因此补做一轮同名 bucket 合并迁移测试。

### 8.1 测试目标

验证以下模式是否可行：

```text
old1: http://OLD1_HOST/BUCKET/<object-key>
new:  http://SEAWEEDFS_HOST/BUCKET/<object-key>

old2: http://OLD2_HOST/BUCKET/<object-key>
new:  http://SEAWEEDFS_HOST/BUCKET/<object-key>
```

测试 bucket：

```text
host-only-demo
```

测试对象：

```text
old1/host-only-demo/from-old1/sample.txt
old2/host-only-demo/from-old2/sample.txt
```

### 8.2 风险确认

同名 bucket 合并迁移前必须做跨源重复 key 扫描：

```text
duplicate_keys=0
```

本次测试的 old1 和 old2 key 没有冲突，因此允许合并迁移到：

```text
sw/host-only-demo
```

如果生产中出现：

```text
old1/BUCKET/a.jpg
old2/BUCKET/a.jpg
```

且两个对象内容不同，则不能直接合并到：

```text
sw/BUCKET/a.jpg
```

必须先做 size/checksum 对比并制定覆盖或改名策略。

### 8.3 迁移结果

执行：

```bash
mc mirror --overwrite --retry --summary old1/host-only-demo sw/host-only-demo
mc mirror --overwrite --retry --summary old2/host-only-demo sw/host-only-demo
```

SeaweedFS 目标清单：

```text
from-old1/sample.txt  33
from-old2/sample.txt  33
```

### 8.4 匿名 HTTP 访问

为了让浏览器或 curl 直接访问测试文件，本轮对测试 bucket 设置了匿名下载能力。

MinIO：

```text
old1 anonymous=download
old2 anonymous=download
```

SeaweedFS：

```text
S3 Gateway 增加 anonymous Read/List
sw policy=download
```

### 8.5 四个对照 URL

old1：

```text
http://172.16.100.132:10100/host-only-demo/from-old1/sample.txt
http://172.16.100.217:8333/host-only-demo/from-old1/sample.txt
```

old2：

```text
http://172.16.100.56:9100/host-only-demo/from-old2/sample.txt
http://172.16.100.217:8333/host-only-demo/from-old2/sample.txt
```

### 8.6 访问验证

四个 URL 均已通过 `curl -fsS` 验证。

返回内容：

```text
host-only old1 sample 2026-05-27
host-only old1 sample 2026-05-27
host-only old2 sample 2026-05-27
host-only old2 sample 2026-05-27
```

结论：

```text
只换 host、不改 bucket 和 object key 的迁移模式可行。
前提是同名 bucket 合并前完成跨源重复 key 检查。
```
