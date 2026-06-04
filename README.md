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

## 文件索引

| 文件 | 说明 |
| --- | --- |
| `minio-migration-test-plan.md` | 迁移测试完整方案 |
| `migration-test-results-2026-05-27.md` | 2026-05-27 实测记录 |
| `production-migration-runbook.md` | 生产迁移 runbook 草案 |
| `server-resource-inventory.md` | 服务器硬件、存储状态与任务分配建议 |
| `hot-cold-tiering-analysis.md` | MinIO 热冷分层改造方案分析 |
| `cold-backup-tiering-test-plan.md` | 旧 MinIO 数据 transition 到冷备 MinIO 的单对象验证方案 |
| `cold-backup-tiering-results-2026-06-04.md` | 2026-06-04 A380 单对象 transition 到 4070S 冷备 MinIO 的实测结果 |
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
