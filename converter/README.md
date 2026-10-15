# converter/ — 1Panel appstore → Helm 转换器

`convert.py`：`(上游树, overlay) → generated/<app>/` 的**纯函数**，同输入重跑输出逐字节一致。

```bash
python3 converter/convert.py --src /path/to/appstore --out generated --sha <upstream-sha>
# deps: pyyaml
```

## 转换规则（v1）

- 每 app 取**最新 semver 版本**，chart version = 上游版本规范化（`v1.2→1.2.0`、`6.1.2-standalone→6.1.2+standalone`）
- **一套通用模板**（deployment/pvc/service/secret/configmap + NOTES），全部差异在 values.yaml
- `formFields` → `values.env`（透传）/ `values.secrets`（password+random → 自动生成 Secret，lookup 幂等）
- compose `environment` 支持 dict 与 list 两种形式；command/entrypoint 里引用的 `${VAR}`（formField）自动注入 env
- `./x:/y` → PVC（10Gi）；`./conf/...` → ConfigMap subPath 挂载
- `healthcheck` → readiness + liveness probe；`mem_limit` → memory limit
- 丢弃：`1panel-network`、`container_name`、`restart`、labels

## 守门（不产坏 chart）

- 阻塞即跳过 + 报告：docker socket / cap_add / devices / network_mode:host / privileged / pid:host / local build / **image 未钉 tag**
- Database 类（tags 含 Database/数据库）与手写四库同名者排除——DB 可靠性走 `charts/` 手写
- 非 semver 目录（`latest/`、变体 `nvidia-0.20.0-cu130` 等）跳过 + 报告——浮动版本不进生态；确需时在 `overlay/apps/<app>/` 人工钉 tag + version
- CI 幂等门：同 SHA 两跑 diff 必须为空；lint 全量 0 failed 否则 job 失败

## v1 已知简化（后续经 overlay/模板升级消化）

- 只转最新版本（上游多版本目录不逐个转换；回滚用 helm rollback）
- ConfigMap 直挂（readOnly），未做 plan 的 initContainer 拷入 PVC（应用运行时改配置的场景走 overlay 加模板）
- `depends_on` 不生成 wait-for initContainer（依赖应用自重试）
- 无 values.schema.json（必填项见各 chart README/NOTES）

设计全文：210 集群仓库 `docs/design-phase4-1panel-helm-plan.md`（本实现按 CF Pages 架构裁剪了 D2/D4 的 Release+warp 拉取路径）。
