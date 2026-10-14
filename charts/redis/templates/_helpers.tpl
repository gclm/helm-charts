{{- define "redis.fullname" -}}
{{- .Release.Name -}}
{{- end -}}

{{- define "redis.password" -}}
{{- if .Values.auth.password -}}
{{- .Values.auth.password -}}
{{- else -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace (include "redis.fullname" .) -}}
{{- if $secret -}}
{{- index $secret.data "REDIS_PASSWORD" | b64dec -}}
{{- else -}}
{{- randAlphaNum 32 -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "redis.labels" -}}
app.kubernetes.io/name: redis
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
