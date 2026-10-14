{{/* fullname = release name（本仓库约定 install 名即 pg/mysql/redis/mongo） */}}
{{- define "postgresql.fullname" -}}
{{- .Release.Name -}}
{{- end -}}

{{/*
postgresql.password: 显式 values > 复用已有 Secret（upgrade 不轮换）> 首次随机生成
*/}}
{{- define "postgresql.password" -}}
{{- if .Values.auth.password -}}
{{- .Values.auth.password -}}
{{- else -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace (include "postgresql.fullname" .) -}}
{{- if $secret -}}
{{- index $secret.data "POSTGRES_PASSWORD" | b64dec -}}
{{- else -}}
{{- randAlphaNum 32 -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "postgresql.labels" -}}
app.kubernetes.io/name: postgresql
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
