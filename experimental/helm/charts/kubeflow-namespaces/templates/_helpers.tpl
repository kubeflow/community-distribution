{{/*
Render a namespace when it is missing or already belongs to this Helm release.
Existing namespaces owned outside this release are skipped to avoid Helm ownership conflicts.
*/}}
{{- define "kubeflow-namespaces.shouldRenderNamespace" -}}
{{- $root := index . "root" -}}
{{- $name := index . "name" -}}
{{- $existing := lookup "v1" "Namespace" "" $name -}}
{{- if not $existing -}}
true
{{- else -}}
{{- $annotations := dict -}}
{{- with $existing.metadata.annotations -}}
{{- $annotations = . -}}
{{- end -}}
{{- if and (eq (default "" (index $annotations "meta.helm.sh/release-name")) $root.Release.Name) (eq (default "" (index $annotations "meta.helm.sh/release-namespace")) $root.Release.Namespace) -}}
true
{{- end -}}
{{- end -}}
{{- end -}}
