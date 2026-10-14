{{- define "mongodb.fullname" -}}
{{- .Release.Name -}}
{{- end -}}

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
keyFile：auth + replSet 必需。upgrade 时 lookup 复用（换了会让副本集成员互拒）。
base64 字符集（字母数字为子集），长度 6-1024 内。
*/}}
{{- define "mongodb.keyfile" -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace (printf "%s-keyfile" (include "mongodb.fullname" .)) -}}
{{- if $secret -}}
{{- index $secret.data "keyfile" | b64dec -}}
{{- else -}}
{{- randAlphaNum 256 -}}
{{- end -}}
{{- end -}}

{{- define "mongodb.labels" -}}
app.kubernetes.io/name: mongodb
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
