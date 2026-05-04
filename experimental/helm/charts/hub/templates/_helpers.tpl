{{/*
Expand the name of the chart.
*/}}
{{- define "model-registry.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "model-registry.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "model-registry.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "model-registry.labels" -}}
helm.sh/chart: {{ include "model-registry.chart" . }}
{{ include "model-registry.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "model-registry.selectorLabels" -}}
app.kubernetes.io/name: {{ include "model-registry.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Common annotations
*/}}
{{- define "model-registry.annotations" -}}
 {{- with .Values.global.annotations }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Create the name of the server service account to use
*/}}
{{- define "model-registry.server.serviceAccountName" -}}
{{- if .Values.server.serviceAccount.create }}
{{- default (printf "%s-server" (include "model-registry.fullname" .)) .Values.server.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.server.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the UI service account to use
*/}}
{{- define "model-registry.ui.serviceAccountName" -}}
{{- if .Values.ui.serviceAccount.create }}
{{- default (printf "%s-ui" (include "model-registry.fullname" .)) .Values.ui.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.ui.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the controller service account to use
*/}}
{{- define "model-registry.controller.serviceAccountName" -}}
{{- if .Values.controller.serviceAccount.create }}
{{- default (printf "%s-controller" (include "model-registry.fullname" .)) .Values.controller.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.controller.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Server labels
*/}}
{{- define "model-registry.server.labels" -}}
{{ include "model-registry.labels" . }}
app.kubernetes.io/component: model-registry-server
{{- with .Values.server.labels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Server selector labels
*/}}
{{- define "model-registry.server.selectorLabels" -}}
{{ include "model-registry.selectorLabels" . }}
app.kubernetes.io/component: model-registry-server
component: model-registry-server
{{- end }}

{{/*
UI fullname
*/}}
{{- define "model-registry.ui.fullname" -}}
{{- printf "%s-ui" (include "model-registry.fullname" .) }}
{{- end }}

{{/*
UI labels
*/}}
{{- define "model-registry.ui.labels" -}}
{{ include "model-registry.labels" . }}
app.kubernetes.io/component: model-registry-ui
{{- end }}

{{/*
UI selector labels
*/}}
{{- define "model-registry.ui.selectorLabels" -}}
{{ include "model-registry.selectorLabels" . }}
app.kubernetes.io/component: model-registry-ui
component: model-registry-ui
{{- end }}

{{/*
Controller fullname
*/}}
{{- define "model-registry.controller.fullname" -}}
{{- printf "%s-controller" (include "model-registry.fullname" .) }}
{{- end }}

{{/*
Controller labels
*/}}
{{- define "model-registry.controller.labels" -}}
{{ include "model-registry.labels" . }}
app.kubernetes.io/component: model-registry-controller
{{- end }}

{{/*
Controller selector labels
*/}}
{{- define "model-registry.controller.selectorLabels" -}}
{{ include "model-registry.selectorLabels" . }}
app.kubernetes.io/component: model-registry-controller
component: model-registry-controller
{{- end }}

{{/*
Create image name for server
*/}}
{{- define "model-registry.server.image" -}}
{{- $registry := .Values.global.imageRegistry -}}
{{- $repository := .Values.server.image.repository -}}
{{- $tag := .Values.server.image.tag | default .Values.global.imageTag -}}
{{- printf "%s/%s:%s" $registry $repository $tag }}
{{- end }}

{{/*
Create image name for UI
*/}}
{{- define "model-registry.ui.image" -}}
{{- $registry := .Values.global.imageRegistry -}}
{{- $repository := .Values.ui.image.repository -}}
{{- $tag := .Values.ui.image.tag | default .Values.global.imageTag -}}
{{- printf "%s/%s:%s" $registry $repository $tag }}
{{- end }}

{{/*
Create image name for controller
*/}}
{{- define "model-registry.controller.image" -}}
{{- $registry := .Values.global.imageRegistry -}}
{{- $repository := .Values.controller.image.repository -}}
{{- $tag := .Values.controller.image.tag | default .Values.global.imageTag -}}
{{- printf "%s/%s:%s" $registry $repository $tag }}
{{- end }}

{{/*
Create image pull policy
*/}}
{{- define "model-registry.imagePullPolicy" -}}
{{- .Values.global.imagePullPolicy }}
{{- end }}

{{/*
Get image pull policy for server
*/}}
{{- define "model-registry.server.imagePullPolicy" -}}
{{- .Values.server.image.pullPolicy | default .Values.global.imagePullPolicy }}
{{- end }}

{{/*
Get image pull policy for UI
*/}}
{{- define "model-registry.ui.imagePullPolicy" -}}
{{- .Values.ui.image.pullPolicy | default .Values.global.imagePullPolicy }}
{{- end }}

{{/*
Get image pull policy for controller
*/}}
{{- define "model-registry.controller.imagePullPolicy" -}}
{{- .Values.controller.image.pullPolicy | default .Values.global.imagePullPolicy }}
{{- end }}

{{/*
Database configuration helpers
*/}}
{{- define "model-registry.database.mysql.enabled" -}}
{{- and (eq .Values.database.type "mysql") .Values.database.mysql.enabled }}
{{- end }}

{{- define "model-registry.database.postgres.enabled" -}}
{{- and (eq .Values.database.type "postgres") .Values.database.postgres.enabled }}
{{- end }}

{{- define "model-registry.database.external.enabled" -}}
{{- and (eq .Values.database.type "external") .Values.database.external.enabled }}
{{- end }}

{{/*
Database connection details
*/}}
{{- define "model-registry.database.host" -}}
{{- if include "model-registry.database.mysql.enabled" . }}
{{- printf "%s-mysql" (include "model-registry.fullname" .) }}
{{- else if include "model-registry.database.postgres.enabled" . }}
{{- printf "%s-postgres" (include "model-registry.fullname" .) }}
{{- else if include "model-registry.database.external.enabled" . }}
{{- .Values.database.external.host }}
{{- end }}
{{- end }}

{{- define "model-registry.database.port" -}}
{{- if include "model-registry.database.mysql.enabled" . }}
{{- .Values.database.mysql.service.port }}
{{- else if include "model-registry.database.postgres.enabled" . }}
{{- .Values.database.postgres.service.port }}
{{- else if include "model-registry.database.external.enabled" . }}
{{- .Values.database.external.port }}
{{- end }}
{{- end }}

{{- define "model-registry.database.name" -}}
{{- if include "model-registry.database.mysql.enabled" . }}
{{- .Values.database.mysql.auth.database }}
{{- else if include "model-registry.database.postgres.enabled" . }}
{{- .Values.database.postgres.auth.database }}
{{- else if include "model-registry.database.external.enabled" . }}
{{- .Values.database.external.database }}
{{- end }}
{{- end }}

{{/*
Database secret name
*/}}
{{- define "model-registry.database.secretName" -}}
{{- if include "model-registry.database.mysql.enabled" . }}
{{- if .Values.database.mysql.auth.existingSecret }}
{{- .Values.database.mysql.auth.existingSecret }}
{{- else }}
{{- printf "%s-mysql-secret" (include "model-registry.fullname" .) }}
{{- end }}
{{- else if include "model-registry.database.postgres.enabled" . }}
{{- if .Values.database.postgres.auth.existingSecret }}
{{- .Values.database.postgres.auth.existingSecret }}
{{- else }}
{{- printf "%s-postgres-secret" (include "model-registry.fullname" .) }}
{{- end }}
{{- else if include "model-registry.database.external.enabled" . }}
{{- if .Values.database.external.existingSecret }}
{{- .Values.database.external.existingSecret }}
{{- else }}
{{- printf "%s-external-db-secret" (include "model-registry.fullname" .) }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Namespace helper
*/}}
{{- define "model-registry.namespace" -}}
{{- .Values.global.namespace | default .Release.Namespace }}
{{- end }}

{{/*
Service name for model registry
*/}}
{{- define "model-registry.service.name" -}}
{{- if .Values.service.name }}
{{- .Values.service.name }}
{{- else }}
{{- printf "%s-service" (include "model-registry.fullname" .) }}
{{- end }}
{{- end }}

{{/*
ConfigMap name for model registry
*/}}
{{- define "model-registry.configMap.name" -}}
{{- printf "%s-configmap" (include "model-registry.fullname" .) }}
{{- end }}

{{/*
Get the full service URL for configuring resources
*/}}
{{- define "model-registry.service.fullhost" -}}
{{- $serviceName := include "model-registry.service.name" . -}}
{{- $namespace := include "model-registry.namespace" . -}}
{{- printf "%s.%s.svc.cluster.local" $serviceName $namespace -}}
{{- end -}}

{{/*
controller simple service account name 
*/}}
{{- define "model-registry.controller.simpleServiceAccountName" -}}
{{- if .Values.controller.useSimpleNames -}}
controller-controller-manager
{{- else -}}
{{- include "model-registry.fullname" . }}-controller-manager
{{- end -}}
{{- end -}}

{{/*
MySQL PVC name
*/}}
{{- define "model-registry.mysql.pvcName" -}}
{{- if .Values.database.resourceNames.mysql.pvcName -}}
{{- .Values.database.resourceNames.mysql.pvcName -}}
{{- else -}}
metadata-mysql
{{- end -}}
{{- end -}}

{{/*
MySQL service name
*/}}
{{- define "model-registry.mysql.serviceName" -}}
{{- if .Values.database.resourceNames.mysql.serviceName -}}
{{- .Values.database.resourceNames.mysql.serviceName -}}
{{- else if .Values.database.mysql.service.name -}}
{{- .Values.database.mysql.service.name -}}
{{- else -}}
model-registry-db
{{- end -}}
{{- end -}}

{{/*
MySQL deployment name
*/}}
{{- define "model-registry.mysql.deploymentName" -}}
{{- if .Values.database.resourceNames.mysql.deploymentName -}}
{{- .Values.database.resourceNames.mysql.deploymentName -}}
{{- else -}}
model-registry-db
{{- end -}}
{{- end -}}

{{/*
Postgres PVC name
*/}}
{{- define "model-registry.postgres.pvcName" -}}
{{- if .Values.database.resourceNames.postgres.pvcName -}}
{{- .Values.database.resourceNames.postgres.pvcName -}}
{{- else -}}
metadata-postgres
{{- end -}}
{{- end -}}

{{/*
Postgres service name
*/}}
{{- define "model-registry.postgres.serviceName" -}}
{{- if .Values.database.resourceNames.postgres.serviceName -}}
{{- .Values.database.resourceNames.postgres.serviceName -}}
{{- else if .Values.database.postgres.service.name -}}
{{- .Values.database.postgres.service.name -}}
{{- else -}}
metadata-postgres-db
{{- end -}}
{{- end -}}

{{/*
Postgres deployment name
*/}}
{{- define "model-registry.postgres.deploymentName" -}}
{{- if .Values.database.resourceNames.postgres.deploymentName -}}
{{- .Values.database.resourceNames.postgres.deploymentName -}}
{{- else -}}
metadata-postgres-db
{{- end -}}
{{- end -}}

{{/*
Service display name for annotations
*/}}
{{- define "model-registry.service.displayName" -}}
{{- .Values.service.annotations.displayName | default "Kubeflow Model Registry" -}}
{{- end -}}

{{/*
Service description for annotations
*/}}
{{- define "model-registry.service.description" -}}
{{- .Values.service.annotations.description | default "An example model registry" -}}
{{- end -}}

{{/*
Validate database configuration
*/}}
{{- define "model-registry.validateDatabase" -}}
{{- $validTypes := list "mysql" "postgres" "external" }}
{{- if not (has .Values.database.type $validTypes) }}
{{- fail (printf "Invalid database.type '%s'. Must be one of: %s" .Values.database.type (join ", " $validTypes)) }}
{{- end }}
{{- if and (eq .Values.database.type "mysql") (not .Values.database.mysql.enabled) }}
{{- fail "database.mysql.enabled must be true when database.type is 'mysql'" }}
{{- end }}
{{- if and (eq .Values.database.type "postgres") (not .Values.database.postgres.enabled) }}
{{- fail "database.postgres.enabled must be true when database.type is 'postgres'" }}
{{- end }}
{{- if and (eq .Values.database.type "external") (not .Values.database.external.enabled) }}
{{- fail "database.external.enabled must be true when database.type is 'external'" }}
{{- end }}
{{- end }} 