# generated/ — 机器生成，禁止手改

此目录存放 1Panel appstore 自动转换的 chart（Phase 4，规划中 ~330 个）。

## 规则（铁律）

- ⛔ **禁止人工修改**：内容由 Actions 定时从上游重新生成，手改会在下次同步被覆盖
- 需要定制 generated 里的应用 → 改 `../overlay/`（补丁层，CI 自动应用到产物上）
- 需要深度定制的应用（如数据库）→ 直接进 `../charts/` 作为手写原生 chart

## 生成流程（Phase 4 落地时生效）

上游 `1Panel-dev/appstore`（renovate 维护镜像 tag）→ converter 转换 → overlay 补丁应用
→ helm lint --strict（不过的进阻塞清单报告，不发布）→ 发布。
