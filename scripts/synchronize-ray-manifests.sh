#!/usr/bin/env bash
# Maintain the upstream Helm render and the wrapper from the same Makefile pin.
set -euo pipefail
SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "${SCRIPT_DIRECTORY}/library.sh"
MANIFESTS_DIRECTORY=$(dirname "$SCRIPT_DIRECTORY")
RAY_DIRECTORY="$MANIFESTS_DIRECTORY/experimental/ray"
CHART_DIRECTORY="$RAY_DIRECTORY/kuberay-operator/helm"
KUBERAY_RELEASE_VERSION=$(sed -n 's/^KUBERAY_RELEASE_VERSION ?= //p' "$RAY_DIRECTORY/Makefile")
KUBERAY_CHART_REPOSITORY=$(sed -n 's/^KUBERAY_HELM_CHART_REPO ?= //p' "$RAY_DIRECTORY/Makefile")
[[ "$KUBERAY_RELEASE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
[[ "$KUBERAY_CHART_REPOSITORY" == https://ray-project.github.io/kuberay-helm/ ]]
require_helm_major_version 4
create_branch "${BRANCH_NAME:-synchronize-ray-manifests-${KUBERAY_RELEASE_VERSION}}"
TEMPORARY_DIRECTORY=$(mktemp -d)
trap 'rm -rf "$TEMPORARY_DIRECTORY"' EXIT
export HELM_CACHE_HOME="$TEMPORARY_DIRECTORY/cache"
export HELM_CONFIG_HOME="$TEMPORARY_DIRECTORY/config"
export HELM_DATA_HOME="$TEMPORARY_DIRECTORY/data"
unset HELM_REPOSITORY_CONFIG HELM_REPOSITORY_CACHE HELM_PLUGINS
update_helm_chart_application_version "$CHART_DIRECTORY/Chart.yaml" "$KUBERAY_RELEASE_VERSION"
sed -i "s/^  version: .*/  version: \"${KUBERAY_RELEASE_VERSION}\"/" "$CHART_DIRECTORY/Chart.yaml"
sed -i "s@kuberay/tree/v[^/]*/helm-chart/@kuberay/tree/v${KUBERAY_RELEASE_VERSION}/helm-chart/@" "$CHART_DIRECTORY/Chart.yaml"
write_generated_file_atomically "$CHART_DIRECTORY/templates/aggregated-roles.yaml" \
  cat "$RAY_DIRECTORY/kuberay-operator/base/aggregated-roles.yaml"
cp -R "$CHART_DIRECTORY" "$TEMPORARY_DIRECTORY/chart"
rm -rf "$TEMPORARY_DIRECTORY/chart/charts"
helm dependency update "$TEMPORARY_DIRECTORY/chart"
# Helm refreshes the lock timestamp even if the resolved dependencies do not
# change. Preserve the checked-in lock when its dependencies and digest match.
python3 - "$CHART_DIRECTORY/Chart.lock" "$TEMPORARY_DIRECTORY/chart/Chart.lock" <<'PY'
import pathlib
import sys
import yaml

current, regenerated = map(pathlib.Path, sys.argv[1:])
new = yaml.safe_load(regenerated.read_text())
old = yaml.safe_load(current.read_text()) if current.exists() else {}
if any(old.get(field) != new[field] for field in ("dependencies", "digest")):
    current.write_bytes(regenerated.read_bytes())
PY
write_generated_file_atomically "$RAY_DIRECTORY/kuberay-operator/base/resources.yaml" \
  helm template --include-crds kuberay-operator \
  "$TEMPORARY_DIRECTORY/chart/charts/kuberay-operator-${KUBERAY_RELEASE_VERSION}.tgz"
helm lint "$TEMPORARY_DIRECTORY/chart" --namespace kubeflow
commit_changes "$MANIFESTS_DIRECTORY" "Synchronize KubeRay ${KUBERAY_RELEASE_VERSION} manifests and Helm wrapper" \
  experimental/ray/kuberay-operator/base/resources.yaml \
  experimental/ray/kuberay-operator/helm/Chart.yaml \
  experimental/ray/kuberay-operator/helm/Chart.lock \
  experimental/ray/kuberay-operator/helm/templates/aggregated-roles.yaml
