{{/*
Dex workload namespace.
*/}}
{{- define "dex.namespace" -}}
{{- .Values.global.authNamespace -}}
{{- end -}}

{{/*
Kubeflow namespace.
*/}}
{{- define "dex.kubeflowNamespace" -}}
{{- .Values.global.kubeflowNamespace -}}
{{- end -}}

{{/*
Istio namespace.
*/}}
{{- define "dex.istioNamespace" -}}
{{- .Values.global.istioNamespace -}}
{{- end -}}

{{/*
oauth2-proxy namespace.
*/}}
{{- define "dex.oauth2ProxyNamespace" -}}
{{- .Values.global.oauth2ProxyNamespace -}}
{{- end -}}
