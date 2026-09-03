{{/*
Render a static Kustomize-generated manifest file while preserving the Go
templates embedded in Istio injector ConfigMaps.
*/}}
{{- define "kubeflow-istio.renderFile" -}}
{{- $root := .root -}}
{{- $content := $root.Files.Get .path -}}
{{- if eq $content "" -}}
{{- fail (printf "required manifest file %s is missing or empty" .path) -}}
{{- end -}}
{{- if .oauth2ProxyService -}}
{{- $service := $root.Values.oauth2Proxy.service | toString -}}
{{- $serviceNamePattern := "^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?)*$" -}}
{{- if or (gt (len $service) 253) (not (regexMatch $serviceNamePattern $service)) -}}
{{- fail "oauth2Proxy.service must be a valid DNS-1123 service name" -}}
{{- end -}}
{{- $portString := $root.Values.oauth2Proxy.port | toString -}}
{{- if not (regexMatch "^[0-9]+$" $portString) -}}
{{- fail "oauth2Proxy.port must be a decimal integer between 1 and 65535" -}}
{{- end -}}
{{- $port := atoi $portString -}}
{{- if or (lt $port 1) (gt $port 65535) -}}
{{- fail "oauth2Proxy.port must be a decimal integer between 1 and 65535" -}}
{{- end -}}
{{- $serviceLiteral := "service: oauth2-proxy.oauth2-proxy.svc.cluster.local" -}}
{{- if not (contains $serviceLiteral $content) -}}
{{- fail (printf "%s does not contain %q, so oauth2Proxy.service cannot be applied; regenerate the chart with scripts/synchronize-istio-manifests.sh" .path $serviceLiteral) -}}
{{- end -}}
{{- $content = replace $serviceLiteral (printf "service: %s" $service) $content -}}
{{- $portPattern := "(service: [^\\n]+\\n[[:space:]]*port: )[0-9]+(\\n[[:space:]]*name: oauth2-proxy)" -}}
{{- if not (regexMatch $portPattern $content) -}}
{{- fail (printf "%s does not match the oauth2-proxy port pattern, so oauth2Proxy.port cannot be applied; regenerate the chart with scripts/synchronize-istio-manifests.sh" .path) -}}
{{- end -}}
{{- $content = regexReplaceAll $portPattern $content (printf "${1}%d${2}" $port) -}}
{{- end -}}
{{- $content -}}
{{- end -}}
