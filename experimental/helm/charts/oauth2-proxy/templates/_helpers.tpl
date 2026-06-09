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
