{{- define "warp.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- .Release.Name -}}
{{- end -}}
{{- end -}}

{{- define "warp.labels" -}}
app.kubernetes.io/name: warp
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
