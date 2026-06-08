# MinIO Migration

MinIO 到 SeaweedFS 迁移测试与生产迁移方案仓库。

## 当前结论

2026-05-27 已完成三台服务器隔离迁移测试：

| 角色 | 服务器 | 用途 |
| --- | --- | --- |
| old1 | A380 `172.16.100.132` | 测试 MinIO 源 1 |
| old2 | A770 `172.16.100.56` | 测试 MinIO 源 2 |
| target | 4070 `172.16.100.217` | SeaweedFS 目标端 + 迁移执行机 |

测试结果：

```text
mc mirror 基础迁移：通过
manifest key + size 对账：通过
sha256 内容校验：通过
增量新增与覆盖：通过
删除策略：已验证
SeaweedFS Filer HTTP：通过
```

2026-06-05 冷备 MinIO 分支已完成真实前缀迁移和恢复验证：

```text
A380 真实前缀 15 个对象 transition 到 4070S 冷备 MinIO：通过
原 A380 host/bucket/key 读取：通过
source 对象路径空间从 635331560 bytes 降到 144912 bytes：通过
冷端新增约 317 MB payload：通过
映射表恢复到 fresh MinIO：通过
```

2026-06-08 已完成已迁移对象删除 smoke：

```text
新建 2 个 8MiB 测试对象 transition 到 4070S 冷备 MinIO：通过
通过 A380 源 bucket/key 删除其中 1 个已迁移对象：通过
被删除对象的 A380 源 URL 和 4070S cold internal URL 均返回 404：通过
另 1 个保留对象仍可通过 A380 源 URL 和 cold URL 访问：通过
```

当前冷备方向：

```text
MinIO lifecycle transition 用于释放旧 MinIO 磁盘空间。
迁移选择应先按 video 表筛出候选 videoId，再迁移该 videoId 对应的完整对象组。
恢复映射必须在迁移批次中生成，不能等源 MinIO metadata 丢失后再补。
如果要求严格灾备，还需要复制、归档或经过大规模恢复演练的 mapping recovery。
```

## 文件索引

| 文件 | 说明 |
| --- | --- |
| `minio-migration-test-plan.md` | 迁移测试完整方案 |
| `migration-test-results-2026-05-27.md` | 2026-05-27 实测记录 |
| `production-migration-runbook.md` | 生产迁移 runbook 草案 |
| `server-resource-inventory.md` | 服务器硬件、存储状态与任务分配建议 |
| `hot-cold-tiering-analysis.md` | MinIO 热冷分层改造方案分析 |
| `cold-backup-migration-overview.md` | 冷备 MinIO 迁移方向总览，包含当前结论、拓扑和证据索引 |
| `production-cold-backup-migration-runbook.md` | 冷备 MinIO 生产迁移操作手册，按小文件 smoke、videoId smoke、生产波次组织 |
| `cold-backup-automation-design.md` | 冷备迁移自动化系统设计，使用 `sucai_meta` 和 `meta_` 表前缀 |
| `cold-backup-automation-implementation-plan.md` | 冷备迁移自动化系统开发计划 |
| `db/sucai_meta_schema.sql` | `sucai_meta` MySQL 元数据 schema |
| `cold_backup_automation/local_state.py` | 迁移执行器本地 SQLite state/outbox |
| `cold_backup_automation/manifest.py` | 迁移批次 JSONL manifest parser |
| `cold_backup_automation/migrator.py` | videoId 迁移计划和本地 outbox 写入 |
| `cold_backup_automation/mc.py` | MinIO `mc` 命令生成工具 |
| `cold_backup_automation/outbox_sync.py` | 本地 outbox 到元数据 API 的同步工具 |
| `cold_backup_automation/cli.py` | 冷备迁移自动化命令行入口 |
| `requirements-cold-backup.txt` | 冷备元数据 API 运行依赖 |
| `cold-backup-tiering-test-plan.md` | 旧 MinIO 数据 transition 到冷备 MinIO 的单对象验证方案 |
| `cold-backup-tiering-results-2026-06-04.md` | 2026-06-04 A380 单对象 transition 到 4070S 冷备 MinIO 的实测结果 |
| `cold-backup-tiering-implementation-runbook.md` | 旧 MinIO 数据转层到冷备 MinIO 的生产实施方案和版本要求 |
| `cold-backup-data-recovery-runbook.md` | 冷备数据恢复 runbook，说明迁移中如何处理 source 到 cold 的映射关系 |
| `real-prefix-tiering-results-2026-06-05.md` | 2026-06-05 A380 真实前缀 15 对象 transition、映射和恢复实测结果 |
| `videoid-business-row-smoke-2026-06-05.md` | 2026-06-05 `videoId=14708948` 业务 row 到 A380 MinIO 对象映射 smoke 结果 |
| `cold-backup-delete-smoke-results-2026-06-08.md` | 2026-06-08 已迁移对象源端删除是否同步清理 cold payload 的 smoke 结果 |
| `minio-tier-version-compat-results-2026-06-04.md` | 2026-06-04 MinIO 2022-11-08 与 2023-12-23 同版本冷备 tiering 兼容性实测 |
| `cold-tier-mapping-recovery-test-plan.md` | 冷端映射表恢复可行性测试方案，用于验证源端 metadata 丢失后的自研恢复可能性 |
| `minio-hybrid-role-mapping-recovery-results-2026-06-05.md` | 2026-06-05 `newminio1` 同时承接冷层和新上传，并用映射表恢复的实测结果 |
| `dual-minio-io-test-plan.md` | 双 MinIO 热冷分层 IO 对比测试方案 |
| `dual-minio-pressure-results-2026-06-03.md` | 2026-06-03 单 HDD vs SSD+HDD 压力测试结果 |
| `real-video-io-saturation-test-plan.md` | 使用真实 `input.MOV` 的单 HDD 饱和与 SSD+HDD 对照压力测试方案 |
| `real-video-io-saturation-results-2026-06-03.md` | 2026-06-03 使用真实 `input.MOV` 的 4070S 本地存储饱和压测结果 |
| `real-video-link1g-results-2026-06-03.md` | 2026-06-03 修复到 1Gbps 后的 A380/A770/4070S 完整链路压测结果 |
| `raw-ssd-archive-test-plan.md` | raw 原片先写 SSD、后台归档 HDD 的测试方案 |
| `raw-ssd-archive-results-2026-06-03.md` | raw 原片先写 SSD、后台归档 HDD 的 S2-a 实测结果 |
| `video-location-index-design.md` | `videoId` 到 SSD/HDD 对象位置索引设计，供测试和后续 Java 改造参考 |
| `run-migration-test.sh` | 4070 上可执行的迁移测试脚本 |
| `scripts/dual_minio_s3bench.py` | S3/MinIO PUT、GET、transcode、push 模拟工具 |
| `scripts/video_location_index.py` | 本地 SQLite 位置索引维护工具 |
| `scripts/reset_dual_minio_test.sh` | 多轮双 MinIO 测试 reset/clean 脚本 |
| `scripts/cold_tier_delete_smoke_remote.sh` | 4070S 上执行的冷备 tier 删除 smoke 脚本，不包含密钥 |
| `scripts/cold_tier_delete_smoke_resume_remote.sh` | 删除 smoke 续跑脚本，用于从已 transition 批次继续清理 rule 和验证删除 |
| `miniochat.md` | 参考建议原文 |

## 安全约定

本仓库不保存：

```text
服务器密码
MinIO access key / secret key
SeaweedFS access key / secret key
GitHub 凭据
```

脚本中的敏感信息通过环境变量注入。
