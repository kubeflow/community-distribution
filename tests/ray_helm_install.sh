#!/usr/bin/env bash
set -euo pipefail
REPOSITORY_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$REPOSITORY_ROOT/scripts/library.sh"
require_helm_major_version 4
CHART_DIRECTORY="$REPOSITORY_ROOT/experimental/ray/kuberay-operator/helm"
TEMPORARY_DIRECTORY=$(mktemp -d)
trap 'rm -rf "$TEMPORARY_DIRECTORY"' EXIT
export HELM_CACHE_HOME="$TEMPORARY_DIRECTORY/cache"
export HELM_CONFIG_HOME="$TEMPORARY_DIRECTORY/config"
export HELM_DATA_HOME="$TEMPORARY_DIRECTORY/data"
unset HELM_REPOSITORY_CONFIG HELM_REPOSITORY_CACHE HELM_PLUGINS
cp -R "$CHART_DIRECTORY" "$TEMPORARY_DIRECTORY/chart"
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm dependency build "$TEMPORARY_DIRECTORY/chart"
# The foundation owns this namespace. Upstream crds/ installs definitions on
# first installation; upgrades require the separately documented schema step.
kubectl get namespace kubeflow >/dev/null
INSTALL_OPTIONS=()
case "${RAY_CRDS_MANAGED_EXTERNALLY:-false}" in
  false) ;;
  true)
    kubectl get crd rayclusters.ray.io rayjobs.ray.io rayservices.ray.io raycronjobs.ray.io >/dev/null
    INSTALL_OPTIONS+=(--skip-crds)
    ;;
  *) echo "RAY_CRDS_MANAGED_EXTERNALLY must be true or false" >&2; exit 1 ;;
esac
helm upgrade --install kuberay-operator "$TEMPORARY_DIRECTORY/chart" \
  --namespace kubeflow --wait --timeout 180s "${INSTALL_OPTIONS[@]}"
kubectl wait --for=condition=Established --timeout=60s \
  crd/rayclusters.ray.io crd/rayjobs.ray.io crd/rayservices.ray.io crd/raycronjobs.ray.io
kubectl -n kubeflow rollout status deployment/kuberay-operator --timeout=180s
