{{/*
Render a static Kustomize-generated manifest file while preserving the Go
templates embedded in Istio injector ConfigMaps.
*/}}
{{- define "kubeflow-istio.renderFile" -}}
{{- $root := .root -}}
{{- $content := $root.Files.Get .path -}}
{{- if .oauth2ProxyService -}}
{{- $content = replace "service: oauth2-proxy.oauth2-proxy.svc.cluster.local" (printf "service: %s" ($root.Values.oauth2Proxy.service | toString)) $content -}}
{{- $content = regexReplaceAll "(service: [^\\n]+\\n[[:space:]]*port: )[0-9]+(\\n[[:space:]]*name: oauth2-proxy)" $content (printf "${1}%d${2}" (int $root.Values.oauth2Proxy.port)) -}}
{{- end -}}
{{- $content -}}
{{- end -}}
