{{/*
Render a static Kustomize-generated manifest file while preserving the Go
templates embedded in Istio injector ConfigMaps.
*/}}
{{- define "kubeflow-istio.validateNamespace" -}}
{{- $name := .name -}}
{{- $value := .value | toString -}}
{{- if or (gt (len $value) 63) (not (regexMatch "^[a-z0-9]([-a-z0-9]*[a-z0-9])?$" $value)) -}}
{{- fail (printf "%s must be a valid DNS-1123 label, got %q" $name $value) -}}
{{- end -}}
{{- end -}}

{{- define "kubeflow-istio.renderFile" -}}
{{- $root := .root -}}
{{- $content := $root.Files.Get .path -}}
{{- $content = replace "istio-system" ($root.Values.global.istioNamespace | toString) $content -}}
{{- $content = replace "kube-system" ($root.Values.global.kubeSystemNamespace | toString) $content -}}
{{- $content = replace "namespace: kubeflow\n" (printf "namespace: %s\n" ($root.Values.global.kubeflowNamespace | toString)) $content -}}
{{- $content = replace "- kubeflow/*" (printf "- %s/*" ($root.Values.global.kubeflowNamespace | toString)) $content -}}
{{- if .oauth2 -}}
{{- $content = replace "service: oauth2-proxy.oauth2-proxy.svc.cluster.local" (printf "service: %s" ($root.Values.oauth2Proxy.service | toString)) $content -}}
{{- $content = regexReplaceAll "(service: [^\\n]+\\n[[:space:]]*port: )[0-9]+(\\n[[:space:]]*name: oauth2-proxy)" $content (printf "${1}%d${2}" (int $root.Values.oauth2Proxy.port)) -}}
{{- end -}}
{{- $content -}}
{{- end -}}
