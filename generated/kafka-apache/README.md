# Kafka (Apache)

采用 Apache Kafka 官方镜像的事件流平台

- 上游: 1Panel-dev/appstore `apps/kafka-apache` @ `857c8b4ce79d`
- 分类: unknown
- 转换产物：不手改（见仓库 README 治理规则）；定制走 `overlay/apps/{app}/`

## 安装

```bash
helm install kafka-apache gclm/kafka-apache
```
