{{- define "trainer.generatedPayload" -}}
{{- $payload := .root.Files.Get .path -}}
{{- if or (eq ($payload | trim) "") (not (regexMatch "(?m)^apiVersion:[[:space:]]*[^[:space:]#]+" $payload)) -}}
{{- fail (printf "required generated payload %q is missing or empty; regenerate Trainer payloads" .path) -}}
{{- end -}}
{{- $payload -}}
{{- end -}}
