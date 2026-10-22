# Zabbix Proxy

Zabbix分布式监控代理，适用于多机房、内网隔离监控场景

- 上游: 1Panel-dev/appstore `apps/zabbix-proxy` @ `488873b3f4e7`
- 分类: unknown
- 转换产物：不手改（见仓库 README 治理规则）；定制走 `overlay/apps/{app}/`

## 安装

```bash
helm install zabbix-proxy gclm/zabbix-proxy
```
