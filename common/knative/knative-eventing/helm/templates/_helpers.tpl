{{- define "knative-eventing.generatedPayload" -}}
{{- $payload := .root.Files.Get .path -}}
{{- if not (regexMatch "(?m)^apiVersion:[[:space:]]*[^[:space:]#]+" $payload) -}}
{{- fail (printf "required generated payload %q is missing or empty; regenerate the chart payloads" .path) -}}
{{- end -}}
{{- $payload -}}
{{- end -}}
