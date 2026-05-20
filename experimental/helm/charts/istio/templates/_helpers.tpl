{{/*
Render a static Kustomize-generated manifest file while preserving the Go
templates embedded in Istio injector ConfigMaps.
*/}}
{{- define "kubeflow-istio.renderFile" -}}
{{- $root := .root -}}
{{- $content := $root.Files.Get .path -}}
{{- $content = replace "istio-system" ($root.Values.global.istioNamespace | toString) $content -}}
{{- $content = replace "kube-system" ($root.Values.global.kubeSystemNamespace | toString) $content -}}
{{- $content = replace "namespace: kubeflow\n" (printf "namespace: %s\n" ($root.Values.global.kubeflowNamespace | toString)) $content -}}
{{- $content = replace "- kubeflow/*" (printf "- %s/*" ($root.Values.global.kubeflowNamespace | toString)) $content -}}
{{- if .oauth2 -}}
{{- $content = replace "service: oauth2-proxy.oauth2-proxy.svc.cluster.local" (printf "service: %s" ($root.Values.oauth2Proxy.service | toString)) $content -}}
{{- $content = replace "        port: 80\n      name: oauth2-proxy" (printf "        port: %d\n      name: oauth2-proxy" (int $root.Values.oauth2Proxy.port)) $content -}}
{{- end -}}
{{- $content -}}
{{- end -}}
