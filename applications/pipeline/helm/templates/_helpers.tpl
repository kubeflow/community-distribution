{{/*
Read a generated payload as plain text.

Payloads live under manifests/ rather than templates/ so Helm never evaluates
them. Kubeflow Pipelines manifests embed Go template delimiters of their own;
evaluated, they would be destroyed.
*/}}
{{- define "kubeflow-pipelines.payload" -}}
{{- $root := .root -}}
{{- $content := $root.Files.Get .path -}}
{{- if eq $content "" -}}
{{- fail (printf "required payload %s is missing or empty; regenerate the chart with scripts/synchronize-pipelines-manifests.sh" .path) -}}
{{- end -}}
{{- $content -}}
{{- end -}}
