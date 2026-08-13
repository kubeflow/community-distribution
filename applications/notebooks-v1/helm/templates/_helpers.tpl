{{/*
Render a generated Kustomize payload verbatim. Helm does not send .Files.Get
content through the template renderer, so Go template delimiters that upstream
manifests legitimately contain are emitted as literal text rather than being
evaluated as part of this chart.
*/}}
{{- define "kubeflow-notebooks.generatedPayload" -}}
{{- $root := index . "root" -}}
{{- $path := index . "path" -}}
{{- $payload := $root.Files.Get $path -}}
{{- $hasResource := regexMatch "(?m)^apiVersion:[[:space:]]*[^[:space:]#]+" $payload -}}
{{- if or (eq ($payload | trim) "") (not $hasResource) -}}
{{- fail (printf "required generated payload %q is missing or empty; regenerate the chart payloads" $path) -}}
{{- end -}}
{{- $payload -}}
{{- end -}}
