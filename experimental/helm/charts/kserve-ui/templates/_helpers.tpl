{{/*
Expand the name of the chart.
*/}}
{{- define "kserve-models-web-app.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "kserve-models-web-app.fullname" -}}
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
{{- define "kserve-models-web-app.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "kserve-models-web-app.labels" -}}
helm.sh/chart: {{ include "kserve-models-web-app.chart" . }}
{{ include "kserve-models-web-app.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- with .Values.commonLabels }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "kserve-models-web-app.selectorLabels" -}}
app.kubernetes.io/component: kserve-models-web-application
kustomize.component: kserve-models-web-application
{{- if .Values.kubeflow.enabled }}
app: kserve
app.kubernetes.io/name: kserve
{{- end }}
{{- end }}

{{/*
Common annotations
*/}}
{{- define "kserve-models-web-app.annotations" -}}
{{- with .Values.global.annotations }}
{{ toYaml . }}
{{- end }}
{{- with .Values.commonAnnotations }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "kserve-models-web-app.serviceAccountName" -}}
{{- if .Values.rbac.serviceAccount.create }}
{{- default (include "kserve-models-web-app.fullname" .) .Values.rbac.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.rbac.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create image name for the web app
*/}}
{{- define "kserve-models-web-app.image" -}}
{{- $registry := .Values.global.imageRegistry -}}
{{- $repository := .Values.app.image.repository -}}
{{- $tag := .Values.app.image.tag | default .Values.global.imageTag -}}
{{- printf "%s/%s:%s" $registry $repository $tag }}
{{- end }}

{{/*
Create image pull policy
*/}}
{{- define "kserve-models-web-app.imagePullPolicy" -}}
{{- .Values.app.image.pullPolicy | default .Values.global.imagePullPolicy }}
{{- end }}

{{/*
Create the namespace
*/}}
{{- define "kserve-models-web-app.namespace" -}}
{{- .Values.global.namespace | default .Release.Namespace }}
{{- end }}

{{/*
Create cluster role name
*/}}
{{- define "kserve-models-web-app.clusterRoleName" -}}
{{- printf "%s-cluster-role" (include "kserve-models-web-app.fullname" .) }}
{{- end }}

{{/*
Create cluster role binding name
*/}}
{{- define "kserve-models-web-app.clusterRoleBindingName" -}}
{{- printf "%s-binding" (include "kserve-models-web-app.fullname" .) }}
{{- end }}

{{/*
Create config map name
*/}}
{{- define "kserve-models-web-app.configMapName" -}}
{{- printf "%s-config" (include "kserve-models-web-app.fullname" .) }}
{{- end }}

{{/*
Create service name
*/}}
{{- define "kserve-models-web-app.serviceName" -}}
{{- include "kserve-models-web-app.fullname" . }}
{{- end }}

{{/*
Create virtual service name
*/}}
{{- define "kserve-models-web-app.virtualServiceName" -}}
{{- include "kserve-models-web-app.fullname" . }}
{{- end }}

{{/*
Create authorization policy name
*/}}
{{- define "kserve-models-web-app.authorizationPolicyName" -}}
{{- include "kserve-models-web-app.fullname" . }}
{{- end }}

{{/*
Create destination host for virtual service
*/}}
{{- define "kserve-models-web-app.destinationHost" -}}
{{- printf "%s.%s.svc.cluster.local" (include "kserve-models-web-app.serviceName" .) (include "kserve-models-web-app.namespace" .) }}
{{- end }}

{{/*
Create Kustomize component labels for backward compatibility
*/}}
{{- define "kserve-models-web-app.kustomizeLabels" -}}
app.kubernetes.io/component: kserve-models-web-application
kustomize.component: kserve-models-web-application
{{- end }}

{{/*
Create KServe common labels
*/}}
{{- define "kserve-models-web-app.kserveLabels" -}}
app: kserve
app.kubernetes.io/name: kserve
{{- end }}
