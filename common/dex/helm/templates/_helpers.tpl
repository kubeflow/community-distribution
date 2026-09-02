{{/*
Directory where connectorCertificateAuthoritySecret is mounted. Connector
configuration refers to files below this path in its rootCAs list.
*/}}
{{- define "dex.certificateAuthorityDirectory" -}}
/etc/dex/certificate-authorities
{{- end -}}
