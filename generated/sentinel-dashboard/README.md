# Sentinel Dashboard

流量控制、熔断降级规则统一配置和管理的入口

- 上游: 1Panel-dev/appstore `apps/sentinel-dashboard` @ `5d9602bbc542`
- 分类: unknown
- 转换产物：不手改（见仓库 README 治理规则）；定制走 `overlay/apps/{app}/`

## 安装

```bash
helm install sentinel-dashboard gclm/sentinel-dashboard
```
