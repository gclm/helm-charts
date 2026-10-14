# gclm/helm-charts

**自维护 Helm Chart 生态仓库** · 发布地址 [charts.xzim.top](https://charts.xzim.top)
（GitHub Actions 构建 → gh-pages 分支 → Cloudflare Pages 托管，与集群可用性解耦）

![release](https://github.com/gclm/helm-charts/actions/workflows/release.yml/badge.svg)

## 快速开始

```bash
helm repo add gclm https://charts.xzim.top
helm repo update
helm search repo gclm/

# 开箱即用：零外部依赖（密码自动生成，备份写 PVC）
helm install pg gclm/postgresql -n db --create-namespace

# 有 NFS 备份机的环境
helm install pg gclm/postgresql -n db --set backup.destination=nfs \
  --set backup.nfs.server=192.168.10.201 --set backup.nfs.path=/hdd-pool/backup/db
```

## 目录结构：按「来源」分治

| 目录 | 内容 | 谁来改 | 修改方式 |
|---|---|---|---|
| [`charts/`](charts/) | **手写原生 chart**（深度应用：数据库等） | 人 | 直接改 + PR 评审 |
| [`generated/`](generated/) | **1Panel appstore 自动转换产物**（Phase 4，~330 应用） | 机器 | ⛔ 禁止手改，下次同步被覆盖 |
| [`overlay/`](overlay/) | **generated 的人工修补层**（values 补丁 / 结构补丁） | 人 | 改补丁，CI 自动应用到产物 |
| [`converter/`](converter/) | Python 转换器源码（Phase 4 入驻） | 人 | 常规代码评审 |

> 原则：**来源决定信任级别与修改权限**。手改 `generated/` 必然丢失——定制走 `overlay/`，深度应用进 `charts/`。

## Chart 规范（准入标准，所有 chart 必须满足）

1. **环境中立**：默认值在任意普通 k8s 集群零配置可用——`storageClass` 默认 `""`（集群默认 SC）、不绑外部地址/凭据
2. **环境差异 values 化**：外部依赖（NFS/S3 等）作为可选项 + 缺参 `fail` 快速报错
3. **必备基线**：readinessProbe、resources requests/limits、密码自动生成（`lookup` 复用，upgrade 不轮换）
4. **有状态应用加两条**：备份 CronJob（`destination: pvc | nfs`，`s3` 规划中）+ 备份新鲜度告警（过期即 Job 失败，Q22 教训）
5. `helm lint --strict` 通过；语义化版本，破坏性变更 bump 次版本并在提交信息注明 `feat!`

已知语义：默认 SC 为 `WaitForFirstConsumer` 时，备份 PVC 首次备份才绑定，`helm install --wait` 可能超时报 `failed`——功能正常，属预期。

## 当前可用 Chart

| Chart | 版本 | 说明 |
|---|---|---|
| [postgresql](charts/postgresql/) | 0.2.0 | PG 17 standalone，`pg_dump -Fc` 逐库备份 + globals |
| [mysql](charts/mysql/) | 0.2.0 | MySQL 8.4，binlog 保留 7 天（PITR 留能力），`mysqldump --single-transaction` |
| [redis](charts/redis/) | 0.2.0 | Redis 8，AOF+RDB 双开，`BGSAVE → --rdb` 拉取 + `redis-check-rdb` 校验 |
| [mongodb](charts/mongodb/) | 0.2.0 | Mongo 8.0 单节点副本集（oplog/PITR），`mongodump --oplog`，keyFile 内置 |

四库均内置 `<name>-backup`（每日，Asia/Shanghai，7 天滚动）与 `<name>-backup-fresh`（06:10 新鲜度检查）两个
CronJob；恢复命令见各 chart 的 `NOTES.txt`；每次大版本升级前须跑一次「删库 → 恢复」演练（已验证记录见
210 集群仓库 `docs/runbook-phase0-2-db-backup.md` 与 `.agents/notes/implemented/backup/`）。

## 发布流水线

push `main`（改动 charts/generated/overlay）→ lint `--strict` → package → 合并历史 index
（[raw gh-pages](https://raw.githubusercontent.com/gclm/helm-charts/gh-pages/index.yaml)，不依赖 CF 状态）
→ 发布 `gh-pages` → CF Pages 自动上线。构建失败 = 不发布，index 永不回退。

## 环境定制模式（chart 中立，环境差异放部署侧）

以 210 集群为例，定制收敛为一个 values 文件（SC 名 + NFS 备份机两项）：

```yaml
# 210-nfs.yaml
persistence:
  storageClass: openebs-lvm
backup:
  destination: nfs
  nfs: {server: 192.168.10.201, path: /hdd-pool/backup/db}
```

```bash
helm upgrade pg gclm/postgresql -n db -f 210-nfs.yaml
```

## 路线图

- [x] 四数据库 chart + 双档备份 + 新鲜度告警（全链路删库恢复演练通过）
- [x] GitHub Actions + CF Pages 分发链
- [ ] **Phase 4**：converter 入驻，1Panel appstore 全量转换进 `generated/` + `overlay/` 消化 42 个阻塞项
- [ ] 备份 `s3` 档（restic → 对象存储，异地容灾）
- [ ] 数据库 `mode: cluster`（主从/副本集 + 跨节点反亲和）
