#!/usr/bin/env bash
# The Helm workflow owns its operator release; this script owns its fixture.
set -euo pipefail
RAY_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$RAY_DIRECTORY"
NAMESPACE=${1:?Pass the existing Kubeflow Profile namespace}
RAY_MANAGED_BY_HELM=${RAY_MANAGED_BY_HELM:-false}
RAY_VERSION=2.56.0
PORT_FORWARD_PROCESS=""
FIXTURE_CREATED=false
OPERATOR_APPLIED=false
NAMESPACE_LABEL_ADDED=false
PROFILE_NAMESPACE_UID=""
case "$RAY_MANAGED_BY_HELM" in
  true|false) ;;
  *) echo "RAY_MANAGED_BY_HELM must be true or false" >&2; exit 1 ;;
esac
# ShellCheck cannot follow the EXIT trap's function call here.
# shellcheck disable=SC2317,SC2329
cleanup() {
  local status=$?
  trap - EXIT
  if [[ -n "$PORT_FORWARD_PROCESS" ]]; then
    kill "$PORT_FORWARD_PROCESS" 2>/dev/null || true
    wait "$PORT_FORWARD_PROCESS" 2>/dev/null || true
  fi
  if [[ "$FIXTURE_CREATED" == true ]]; then
    kubectl -n "$NAMESPACE" delete -f raycluster_example.yaml --ignore-not-found --wait=true --timeout=120s || status=1
    local remaining=1
    for ((attempt=0; attempt<60; attempt++)); do
      remaining=$(kubectl -n "$NAMESPACE" get pods -l ray.io/cluster=kubeflow-raycluster -o json | jq '.items | length') || break
      [[ "$remaining" == 0 ]] && break
      sleep 2
    done
    if [[ "$remaining" != 0 ]]; then
      echo "Ray fixture Pods did not disappear" >&2
      status=1
    fi
  fi
  if [[ "$OPERATOR_APPLIED" == true ]]; then
    kustomize build kuberay-operator/overlays/kubeflow | kubectl -n kubeflow delete --ignore-not-found -f - || status=1
  fi
  if [[ "$NAMESPACE_LABEL_ADDED" == true ]]; then
    # Remove only the label added by this invocation, on the same Namespace.
    # The atomic tests refuse cleanup if either identity or label changed.
    kubectl patch namespace "$NAMESPACE" --type=json --patch \
      "[{\"op\":\"test\",\"path\":\"/metadata/uid\",\"value\":\"$PROFILE_NAMESPACE_UID\"},{\"op\":\"test\",\"path\":\"/metadata/labels/istio-injection\",\"value\":\"enabled\"},{\"op\":\"remove\",\"path\":\"/metadata/labels/istio-injection\"}]" \
      || status=1
  fi
  exit "$status"
}
trap cleanup EXIT
kubectl get namespace "$NAMESPACE" >/dev/null
# A temporary fixture must not overwrite existing Profile configuration.
ISTIO_INJECTION=$(kubectl get namespace "$NAMESPACE" -o jsonpath='{.metadata.labels.istio-injection}')
if [[ -n "$ISTIO_INJECTION" && "$ISTIO_INJECTION" != enabled ]]; then
  echo "The Profile namespace must allow istio-injection=enabled; refusing its existing value" >&2
  exit 1
fi
# Every object in the fixture must be absent before apply and cleanup can own it.
FIXTURE_RESOURCES=(
  authorizationpolicy.security.istio.io/allow-ray-workers-head
  service/raycluster-istio-headless-svc
)
# The legacy path can install Ray for the first time. Without its definition,
# no RayCluster can exist; other read failures must stop the test.
RAY_DEFINITION=$(kubectl get crd rayclusters.ray.io --ignore-not-found -o name)
if [[ -n "$RAY_DEFINITION" ]]; then
  FIXTURE_RESOURCES+=(raycluster/kubeflow-raycluster)
fi
for fixture_resource in "${FIXTURE_RESOURCES[@]}"; do
  existing_fixture=$(kubectl -n "$NAMESPACE" get "$fixture_resource" --ignore-not-found -o name)
  if [[ -n "$existing_fixture" ]]; then
    echo "The test fixture $fixture_resource already exists" >&2
    exit 1
  fi
done
if [[ -z "$ISTIO_INJECTION" ]]; then
  PROFILE_NAMESPACE_UID=$(kubectl get namespace "$NAMESPACE" -o jsonpath='{.metadata.uid}')
  [[ -n "$PROFILE_NAMESPACE_UID" ]] || { echo "The Profile Namespace UID is missing" >&2; exit 1; }
  kubectl label namespace "$NAMESPACE" istio-injection=enabled
  NAMESPACE_LABEL_ADDED=true
fi
if [[ "$RAY_MANAGED_BY_HELM" == false ]]; then
  kustomize build kuberay-operator/overlays/kubeflow | kubectl -n kubeflow apply --server-side -f -
  OPERATOR_APPLIED=true
fi
kubectl -n kubeflow rollout status deployment/kuberay-operator --timeout=180s
FIXTURE_CREATED=true
kubectl -n "$NAMESPACE" apply -f raycluster_example.yaml
# The example contains Profile-specific routing references. Its supported
# namespace is documented; change the fixture explicitly for other Profiles.
for ((attempt=0; attempt<60; attempt++)); do
  if [[ $(kubectl -n "$NAMESPACE" get pods -l ray.io/cluster=kubeflow-raycluster -o json | jq '.items | length') -ge 2 ]]; then
    break
  fi
  sleep 3
done
kubectl -n "$NAMESPACE" wait --for=condition=Ready pod -l ray.io/cluster=kubeflow-raycluster --timeout=180s
HEAD_POD=$(kubectl -n "$NAMESPACE" get pods -l ray.io/cluster=kubeflow-raycluster,ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')
# Submit real distributed work and check its result, not only dashboard health.
kubectl -n "$NAMESPACE" exec -i "$HEAD_POD" -c ray-head -- python - <<'PY'
import ray

ray.init(address="auto")

@ray.remote
def square(value):
    return value * value

result = ray.get([square.remote(value) for value in range(10)], timeout=60)
assert result == [value * value for value in range(10)], result
print("Ray distributed task results verified:", result)
ray.shutdown()
PY
kubectl -n "$NAMESPACE" port-forward svc/kubeflow-raycluster-head-svc 8265:8265 &
PORT_FORWARD_PROCESS=$!
for ((attempt=0; attempt<30; attempt++)); do
  if output=$(curl --fail --silent --show-error --max-time 3 localhost:8265/api/version); then
    echo "$output" | jq -e --arg version "$RAY_VERSION" '.ray_version == $version'
    exit 0
  fi
  sleep 2
done
echo "Ray dashboard did not become reachable" >&2
exit 1
