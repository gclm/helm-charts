# converter/ — 1Panel appstore → Helm 转换器（Phase 4 入驻）

Python 转换器 + 上游同步逻辑。设计输入与实测数据见 210 集群仓库
`docs/design-phase4-1panel-helm-registry.md`（330/372 可自动转，原型已过 --dry-run=server）。

纪律：幂等、不手改生成物、失败即报警。
