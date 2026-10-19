{{/*
fullname = release 名（本仓库约定 install 名即资源前缀，如 pg / redis）。
截断到 38：CronJob 名最长 52，而 `<fullname>-backup-verify` 共 14 字符，
故 fullname 必须 <= 38 —— 实测 release 名 39 字符会被 API 拒绝。
*/}}
{{- define "mongodb.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 38 | trimSuffix "-" -}}
{{- else -}}
{{- .Release.Name | trunc 38 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}

{{/*
mongodb.password: 显式 values > 复用已有 Secret（upgrade 不轮换）> 首次随机生成
*/}}
{{- define "mongodb.password" -}}
{{- if .Values.auth.password -}}
{{- .Values.auth.password -}}
{{- else -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace (include "mongodb.fullname" .) -}}
{{- if $secret -}}
{{- index $secret.data "MONGO_ROOT_PASSWORD" | b64dec -}}
{{- else -}}
{{- randAlphaNum 32 -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
mongodb.memberSvc: StatefulSet 成员的稳定 DNS（4 段 .svc 形式，ordinal 0）。
不写 cluster.local —— zone 交给 resolver 的 search 域补，
这样换 cluster domain 不会静默断连；跨 ns 也可解析。
*/}}
{{- define "mongodb.memberSvc" -}}
{{- printf "%s-0.%s.%s.svc" (include "mongodb.fullname" .) (include "mongodb.fullname" .) .Release.Namespace -}}
{{- end -}}

{{/*
mongodb.memberHosts: 全成员逗号分隔列表，供 libpq DSN 选主
（target_session_attrs=read-write 时客户端自动挑到可写主库）。
*/}}
{{- define "mongodb.memberHosts" -}}
{{- $full := include "mongodb.fullname" . -}}
{{- $ns := .Release.Namespace -}}
{{- $n := 2 -}}
{{- if and .Values.cluster .Values.cluster.dataMembers -}}
{{- $n = .Values.cluster.dataMembers | int -}}
{{- end -}}
{{- $out := list -}}
{{- range $i := until (int $n) -}}
{{- $out = append $out (printf "%s-%d.%s.%s.svc" $full $i $full $ns) -}}
{{- end -}}
{{- join "," $out -}}
{{- end -}}

{{- define "mongodb.labels" -}}
app.kubernetes.io/name: mongodb
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* mongodb.keyfile: 副本集内部认证 keyfile，独立 Secret */}}
{{- define "mongodb.keyfile" -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace (printf "%s-keyfile" (include "mongodb.fullname" .)) -}}
{{- if $secret -}}
{{- index $secret.data "keyfile" | b64dec -}}
{{- else -}}
{{- randAlphaNum 256 -}}
{{- end -}}
{{- end -}}
