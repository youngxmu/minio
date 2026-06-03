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
| `run-migration-test.sh` | 4070 上可执行的迁移测试脚本 |
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
