{{- define "mysql.fullname" -}}
{{- .Release.Name -}}
{{- end -}}

{{- define "mysql.password" -}}
{{- if .Values.auth.password -}}
{{- .Values.auth.password -}}
{{- else -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace (include "mysql.fullname" .) -}}
{{- if $secret -}}
{{- index $secret.data "MYSQL_ROOT_PASSWORD" | b64dec -}}
{{- else -}}
{{- randAlphaNum 32 -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "mysql.labels" -}}
app.kubernetes.io/name: mysql
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
