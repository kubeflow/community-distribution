{{/*
oauth2-proxy workload namespace.
*/}}
{{- define "oauth2-proxy.namespace" -}}
{{- .Values.global.oauth2ProxyNamespace -}}
{{- end -}}

{{/*
Istio namespace.
*/}}
{{- define "oauth2-proxy.istioNamespace" -}}
{{- .Values.global.istioNamespace -}}
{{- end -}}

{{/*
Kubeflow namespace.
*/}}
{{- define "oauth2-proxy.kubeflowNamespace" -}}
{{- .Values.global.kubeflowNamespace -}}
{{- end -}}

{{/*
Render a JWT rule for Istio RequestAuthentication.
*/}}
{{- define "oauth2-proxy.m2mJwtRule" -}}
- forwardOriginalToken: true
  fromHeaders:
  - name: Authorization
    prefix: "Bearer "
  issuer: {{ .issuer }}
{{- if .jwksUri }}
  jwksUri: {{ .jwksUri }}
{{- end }}
  outputClaimToHeaders:
  - claim: sub
    header: kubeflow-userid
  - claim: groups
    header: kubeflow-groups
{{- end -}}
