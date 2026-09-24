#!/usr/bin/env bash
# Install one Hub platform release; values are supplied, never regenerated here.
set -euo pipefail
component=${1:?Usage: hub_helm_install.sh registry|catalog PRIVATE_VALUES_FILE}
values_file=${2:?Supply a private Helm values file}
case "$component" in
  registry) chart=applications/hub/helm; namespace=kubeflow-user-example-com ;;
  catalog) chart=applications/hub/helm-catalog; namespace=kubeflow ;;
  *) echo "Unsupported Hub component: $component" >&2; exit 1 ;;
esac
[[ -f "$values_file" ]] || { echo "Values file does not exist" >&2; exit 1; }
kubectl get namespace "$namespace" >/dev/null
helm upgrade --install "hub-model-${component}" "$chart" --namespace "$namespace" \
  --values "$values_file" --wait --timeout 5m
HUB_MANAGED_BY_HELM=true "./tests/model_${component}_install.sh"
