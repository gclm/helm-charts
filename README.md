# gclm/helm-charts

自维护 Helm Chart 仓库（210 集群应用生态）。发布地址：**https://charts.xzim.top**（Cloudflare Pages → `gh-pages` 分支）。

## 结构

```
charts/       手写原生 chart（DB 先行：postgresql / mysql / redis / mongodb）
scripts/      工具脚本（Phase 4: 1Panel appstore 转换器将进这里）
generated/    （规划中）1Panel appstore 自动转换产物，不手改
```

## 发布流程

push 到 `main`（改动 `charts/**`）→ GitHub Actions：`helm lint --strict` → package →
合并历史 index → 发布到 `gh-pages` 分支 → Cloudflare Pages 自动上线。

CF Pages 配置（一次性，dashboard）：连接本仓库，production branch = `gh-pages`，
build command 留空，output dir = `/`，custom domain = `charts.xzim.top`。

## 使用

```bash
helm repo add gclm https://charts.xzim.top
helm repo update
helm search repo gclm/

# 例：装 PostgreSQL（密码留空则自动生成并写入 Secret，upgrade 自动复用）
helm install pg gclm/postgresql -n db --create-namespace
```

## Chart 约定（四库同构）

- 单副本 StatefulSet + PVC（`persistence.storageClass` 默认 `""` = 集群默认 SC）
- 备份：CronJob + 新鲜度告警，`timeZone: Asia/Shanghai`，7 天滚动。**落点三档**：
  - `backup.destination: pvc`（**默认**）——备份写专用 PVC，零外部依赖，任何集群开箱即用
  - `backup.destination: nfs`——备份写外部 NFS（需 `backup.nfs.server/path`，适合有独立备份机的环境）
  - `s3`（规划中，restic/对象存储，异地容灾档）
  - 注：若集群默认 SC 为 `WaitForFirstConsumer`（local-path/localpv 常见），备份 PVC 在首次备份时才绑定，
    `helm install --wait` 可能因此超时报 `failed`——资源会正常工作，属预期；或安装时不加 `--wait`
- 备份新鲜度告警：每库一个 `*-backup-fresh` CronJob，最新备份目录超过 `freshnessAlert.maxAgeHours`（默认 26h）则 Job 失败（Q22 教训：备份静默死亡不可接受）
- 密码：`auth.password` 显式指定，或留空自动生成（`lookup` 复用，upgrade 不轮换）
- chart 保持环境中立；某环境的定制（SC 名、NFS 地址等）用部署时 values override 注入

```bash
# 开箱即用（备份进 PVC）
helm install pg gclm/postgresql -n db --create-namespace
# 有 NFS 备份机的环境
helm install pg gclm/postgresql -n db --set backup.destination=nfs \
  --set backup.nfs.server=192.168.10.201 --set backup.nfs.path=/hdd-pool/backup/db
```

## 恢复演练纪律

每个 chart 的 NOTES.txt 附恢复命令；每次大版本升级前必须跑一次「删库 → 恢复」演练。
已验证的完整演练记录见 210 集群仓库 `docs/runbook-phase0-2-db-backup.md` 与
`.agents/notes/implemented/backup/2026-10-14-db-backup-phase0-2.md`。
