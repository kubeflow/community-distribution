#!/usr/bin/env bash
# Destructive release lifecycle test: run only in a disposable test cluster.
set -euo pipefail
[[ "${RUN_HELM_LIFECYCLE_TESTS:-}" == true ]] || {
  echo "Set RUN_HELM_LIFECYCLE_TESTS=true only for a disposable test cluster" >&2
  exit 1
}
REPOSITORY_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PROFILE_NAMESPACE=${1:-kubeflow-user-example-com}
TEMPORARY_DIRECTORY=$(mktemp -d)
trap 'rm -rf "$TEMPORARY_DIRECTORY"' EXIT
export HELM_CACHE_HOME="$TEMPORARY_DIRECTORY/cache"
export HELM_CONFIG_HOME="$TEMPORARY_DIRECTORY/config"
export HELM_DATA_HOME="$TEMPORARY_DIRECTORY/data"
unset HELM_REPOSITORY_CONFIG HELM_REPOSITORY_CACHE HELM_PLUGINS
cp -R "$REPOSITORY_ROOT/experimental/ray/kuberay-operator/helm" "$TEMPORARY_DIRECTORY/chart"
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm dependency build "$TEMPORARY_DIRECTORY/chart"
CHART_DIRECTORY="$TEMPORARY_DIRECTORY/chart"
helm status kuberay-operator -n kubeflow >/dev/null
kubectl get namespace "$PROFILE_NAMESPACE" >/dev/null
if kubectl -n "$PROFILE_NAMESPACE" get rayjob helm-lifecycle-held >/dev/null 2>&1; then
  echo "Refusing to replace an existing lifecycle fixture" >&2
  exit 1
fi
python3 - "$REPOSITORY_ROOT/experimental/ray/raycluster_example.yaml" > "$TEMPORARY_DIRECTORY/job.yaml" <<'PY'
import sys
import yaml

cluster = next(item for item in yaml.safe_load_all(open(sys.argv[1])) if item["kind"] == "RayCluster")
yaml.safe_dump({
    "apiVersion": "ray.io/v1",
    "kind": "RayJob",
    "metadata": {"name": "helm-lifecycle-held"},
    "spec": {
        "suspend": True,
        "shutdownAfterJobFinishes": True,
        "entrypoint": "python -c 'print(42)'",
        "rayClusterSpec": cluster["spec"],
    },
}, sys.stdout)
PY
kubectl -n "$PROFILE_NAMESPACE" create -f "$TEMPORARY_DIRECTORY/job.yaml"
# KubeRay 1.6.2 checks suspend before creating the RayCluster. Wait for that
# state before recording identity; this fixture measures retention, not work.
kubectl -n "$PROFILE_NAMESPACE" wait --for=jsonpath='{.status.jobDeploymentStatus}'=Suspended \
  rayjob/helm-lifecycle-held --timeout=120s
snapshot() {
  kubectl get crd rayclusters.ray.io rayjobs.ray.io rayservices.ray.io raycronjobs.ray.io -o json \
    | jq -S '[.items[] | {name: .metadata.name, uid: .metadata.uid, spec: .spec}] | sort_by(.name)'
  kubectl -n "$PROFILE_NAMESPACE" get rayjob helm-lifecycle-held -o json \
    | jq -S '{uid: .metadata.uid, spec: .spec}'
  kubectl get namespace kubeflow "$PROFILE_NAMESPACE" -o json \
    | jq -S '[.items[] | {name: .metadata.name, uid: .metadata.uid}] | sort_by(.name)'
}
snapshot > "$TEMPORARY_DIRECTORY/before"
verify_retention() {
  snapshot > "$TEMPORARY_DIRECTORY/after"
  cmp "$TEMPORARY_DIRECTORY/before" "$TEMPORARY_DIRECTORY/after"
}
helm show crds "$CHART_DIRECTORY" > "$TEMPORARY_DIRECTORY/definitions.yaml"
# Exercise the explicit same-version schema maintenance path as well as Helm.
kubectl apply --server-side --field-manager=kubeflow-crd-maintenance -f "$TEMPORARY_DIRECTORY/definitions.yaml"
verify_retention
helm upgrade kuberay-operator "$CHART_DIRECTORY" -n kubeflow --wait --timeout 180s
verify_retention
ROLLBACK_REVISION=$(helm status kuberay-operator -n kubeflow -o json | jq -r .version)
helm upgrade kuberay-operator "$CHART_DIRECTORY" -n kubeflow \
  --set kuberay-operator.replicas=2 --wait --timeout 180s
[[ $(kubectl -n kubeflow get deployment kuberay-operator -o jsonpath='{.spec.replicas}') == 2 ]]
verify_retention
helm rollback kuberay-operator "$ROLLBACK_REVISION" -n kubeflow --wait --timeout 180s
[[ $(kubectl -n kubeflow get deployment kuberay-operator -o jsonpath='{.spec.replicas}') == 1 ]]
verify_retention
helm uninstall kuberay-operator -n kubeflow --wait --timeout 180s
verify_retention
if kubectl -n kubeflow get deployment kuberay-operator >/dev/null 2>&1; then
  echo "Uninstall left the operator Deployment behind" >&2
  exit 1
fi
helm install kuberay-operator "$CHART_DIRECTORY" -n kubeflow --skip-crds --wait --timeout 180s
kubectl -n kubeflow rollout status deployment/kuberay-operator --timeout=180s
verify_retention
kubectl -n "$PROFILE_NAMESPACE" delete -f "$TEMPORARY_DIRECTORY/job.yaml" --wait=true --timeout=120s
# Recovered reconciliation must also run real distributed work successfully.
RAY_MANAGED_BY_HELM=true "$REPOSITORY_ROOT/experimental/ray/test.sh" "$PROFILE_NAMESPACE"
echo "KubeRay upgrades, rollback, uninstall retention and reinstall recovery passed"
