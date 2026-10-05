#!/usr/bin/env bash
# Destructive release lifecycle. Run it only on a disposable cluster that no
# later test needs; the knative_serving_helm_lifecycle job in
# .github/workflows/knative_test.yaml does.
set -euo pipefail
namespace=${1:?Usage: knative_serving_helm_lifecycle_test.sh PROFILE_NAMESPACE}
chart=common/knative/knative-serving/helm
fixture=knative-helm-routing
evidence=logs/knative-serving-lifecycle
temporary=$(mktemp -d)
capture_diagnostics() {
    local directory="$evidence/$1"
    mkdir -p "$directory" || return 0
    kubectl get deployments,pods,events -n knative-serving --request-timeout=10s -o yaml >"$directory/resources.yaml" 2>&1 || true
    kubectl get services.serving.knative.dev,revisions.serving.knative.dev,pods,events -n "$namespace" --request-timeout=10s -o yaml >"$directory/fixture.yaml" 2>&1 || true
    for deployment in activator autoscaler controller net-istio-controller net-istio-webhook webhook; do
        kubectl logs "deployment/$deployment" -n knative-serving --request-timeout=10s --tail=100 >"$directory/$deployment.log" 2>&1 || true
    done
}
cleanup() {
    local status=$?
    rm -rf "$temporary"
    if (( status != 0 )); then
        capture_diagnostics failure
        echo "Preserving the Knative Serving fixture after failure; see $evidence/." >&2
    else
        kubectl delete services.serving.knative.dev "$fixture" -n "$namespace" --ignore-not-found || status=$?
        kubectl delete authorizationpolicy "$fixture" -n "$namespace" --ignore-not-found || status=$?
    fi
    exit "$status"
}
trap cleanup EXIT
controller_annotation() {
    kubectl get deployment/controller -n knative-serving \
        -o jsonpath='{.spec.template.metadata.annotations.tests\.kubeflow\.org/lifecycle}'
}
./tests/knative_serving_helm_admission_test.sh
KNATIVE_HELM_KEEP_FIXTURE=true ./tests/knative_serving_helm_smoke_test.sh "$namespace"
uid=$(kubectl get services.serving.knative.dev "$fixture" -n "$namespace" -o jsonpath='{.metadata.uid}')
namespace_uid=$(kubectl get namespace knative-serving -o jsonpath='{.metadata.uid}')
capture_diagnostics before-unchanged-upgrade
helm upgrade knative-serving "$chart" -n kubeflow --wait --timeout 10m
./tests/knative_serving_helm_admission_test.sh
revision=$(helm history knative-serving -n kubeflow -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)[-1]["revision"])')
cp -a "$chart" "$temporary/chart"
# A disposable candidate changes the controller Pod template, proving a real
# workload rollout instead of only incrementing the stored release revision.
python3 - "$temporary/chart/manifests/platform-resources.yaml" <<'PYTHON'
import sys
from pathlib import Path
import yaml
path = Path(sys.argv[1])
resources = list(yaml.safe_load_all(path.read_text()))
controllers = [r for r in resources if r and r["kind"] == "Deployment" and r["metadata"]["name"] == "controller"]
assert len(controllers) == 1, "Expected one controller Deployment"
controllers[0]["spec"]["template"]["metadata"].setdefault("annotations", {})["tests.kubeflow.org/lifecycle"] = "changed"
path.write_text(yaml.safe_dump_all(resources, sort_keys=False))
PYTHON
capture_diagnostics before-changed-upgrade
helm upgrade knative-serving "$temporary/chart" -n kubeflow --wait --timeout 10m
kubectl rollout status deployment/controller -n knative-serving --timeout=120s
# A standalone assignment lets a failed read stop the script.
changed_annotation=$(controller_annotation)
if [[ "$changed_annotation" != changed ]]; then
    echo "The changed upgrade did not reach the live controller Pod template" >&2
    exit 1
fi
./tests/knative_serving_helm_admission_test.sh
KNATIVE_HELM_KEEP_FIXTURE=true ./tests/knative_serving_helm_smoke_test.sh "$namespace"
capture_diagnostics before-rollback
helm rollback knative-serving "$revision" -n kubeflow --wait --timeout 10m
kubectl rollout status deployment/controller -n knative-serving --timeout=120s
restored_annotation=$(controller_annotation)
if [[ -n "$restored_annotation" ]]; then
    echo "Rollback did not restore the live controller Pod template" >&2
    exit 1
fi
./tests/knative_serving_helm_admission_test.sh
KNATIVE_HELM_KEEP_FIXTURE=true ./tests/knative_serving_helm_smoke_test.sh "$namespace"
capture_diagnostics before-uninstall
helm uninstall knative-serving -n kubeflow --wait --timeout 10m
[[ $(kubectl get services.serving.knative.dev "$fixture" -n "$namespace" -o jsonpath='{.metadata.uid}') == "$uid" ]]
[[ $(kubectl get namespace knative-serving -o jsonpath='{.metadata.uid}') == "$namespace_uid" ]]
kubectl get -f "$chart/manifests/platform-crds.yaml" >/dev/null
./tests/knative_serving_helm_install.sh
KNATIVE_HELM_KEEP_FIXTURE=true ./tests/knative_serving_helm_smoke_test.sh "$namespace"
[[ $(kubectl get services.serving.knative.dev "$fixture" -n "$namespace" -o jsonpath='{.metadata.uid}') == "$uid" ]]
echo "Serving lifecycle passed: unchanged upgrade, live changed upgrade and rollback, retained objects and route recovery."
