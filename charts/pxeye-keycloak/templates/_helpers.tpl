{{- define "pxeye-keycloak.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "pxeye-keycloak.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "pxeye-keycloak.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{- define "pxeye-keycloak.labels" -}}
app.kubernetes.io/name: {{ include "pxeye-keycloak.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end }}

{{- define "pxeye-keycloak.selectorLabels" -}}
app.kubernetes.io/name: {{ include "pxeye-keycloak.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
