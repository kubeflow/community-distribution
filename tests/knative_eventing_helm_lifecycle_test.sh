#!/usr/bin/env bash
# Destructive Eventing lifecycle; use only the disposable integration cluster.
set -euo pipefail
chart=common/knative/knative-eventing/helm
namespace=knative-eventing
fixture=knative-helm-events
temporary=$(mktemp -d)
cleanup() {
    rm -rf "$temporary"
    kubectl delete pingsource,eventtype,service,deployment "$fixture" -n "$namespace" --ignore-not-found
}
trap cleanup EXIT
KNATIVE_HELM_KEEP_FIXTURE=true ./tests/knative_eventing_helm_smoke_test.sh
kubectl apply -n "$namespace" -f - <<EOF
apiVersion: eventing.knative.dev/v1beta2
kind: EventType
metadata:
  name: $fixture
spec:
  type: dev.knative.sources.ping
  source: https://knative.example/helm-lifecycle
  reference:
    apiVersion: v1
    kind: Service
    name: $fixture
EOF
ping_path="/apis/sources.knative.dev/v1/namespaces/$namespace/pingsources/$fixture"
converted_ping_path="/apis/sources.knative.dev/v1beta2/namespaces/$namespace/pingsources/$fixture"
eventtype_path="/apis/eventing.knative.dev/v1beta2/namespaces/$namespace/eventtypes/$fixture"
converted_eventtype_path="/apis/eventing.knative.dev/v1beta3/namespaces/$namespace/eventtypes/$fixture"
uid=$(kubectl get --raw "$ping_path" | python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["uid"])')
eventtype_uid=$(kubectl get --raw "$eventtype_path" | python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["uid"])')
namespace_uid=$(kubectl get namespace "$namespace" -o jsonpath='{.metadata.uid}')
# Both configured conversion APIs must work while the webhook is available.
kubectl get --raw "$converted_ping_path" >/dev/null
kubectl get --raw "$converted_eventtype_path" >/dev/null
kubectl rollout status deployment/pingsource-mt-adapter -n "$namespace" --timeout=120s
capture_adapter() {
    kubectl get deployment/pingsource-mt-adapter -n "$namespace" -o json | \
        python3 -c 'import json,sys
deployment=json.load(sys.stdin)
print(json.dumps({"spec":deployment["spec"],"generation":deployment["metadata"]["generation"]}, sort_keys=True))'
    kubectl get pods -n "$namespace" -l eventing.knative.dev/source=ping-source-controller -o json | \
        python3 -c 'import json, sys

pods = [
    pod
    for pod in json.load(sys.stdin)["items"]
    if not pod["metadata"].get("deletionTimestamp")
]
assert pods and all(
    any(
        condition["type"] == "Ready" and condition["status"] == "True"
        for condition in pod.get("status", {}).get("conditions", [])
    )
    for pod in pods
), "Expected healthy, active adapter Pods"
print(json.dumps(sorted(pod["metadata"]["uid"] for pod in pods)))'
}
capture_adapter >"$temporary/adapter-before"
for attempt in 1 2; do
    helm upgrade knative-eventing "$chart" -n kubeflow --reset-values --set installation.phase=complete --wait --timeout 10m
    # A new event gives the adapter time to process work after each upgrade.
    KNATIVE_HELM_KEEP_FIXTURE=true ./tests/knative_eventing_helm_smoke_test.sh
    capture_adapter >"$temporary/adapter-after"
    if ! diff -u "$temporary/adapter-before" "$temporary/adapter-after"; then
        echo "Unchanged upgrade $attempt rewrote the PingSource adapter or replaced its Pod" >&2
        exit 1
    fi
done
revision=$(helm history knative-eventing -n kubeflow -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)[-1]["revision"])')
cp -a "$chart" "$temporary/chart"
python3 - "$temporary/chart/manifests/platform-resources.yaml" <<'PYTHON'
import sys
from pathlib import Path
import yaml
path = Path(sys.argv[1])
resources = list(yaml.safe_load_all(path.read_text()))
controllers = [
    resource
    for resource in resources
    if resource
    and resource["kind"] == "Deployment"
    and resource["metadata"]["name"] == "eventing-controller"
]
assert len(controllers) == 1, "Expected one controller Deployment"
controllers[0]["spec"]["template"]["metadata"].setdefault("annotations", {})["tests.kubeflow.org/lifecycle"] = "changed"
path.write_text(yaml.safe_dump_all(resources, sort_keys=False))
PYTHON
helm upgrade knative-eventing "$temporary/chart" -n kubeflow --wait --timeout 10m
kubectl rollout status deployment/eventing-controller -n "$namespace" --timeout=120s
KNATIVE_HELM_KEEP_FIXTURE=true ./tests/knative_eventing_helm_smoke_test.sh
helm rollback knative-eventing "$revision" -n kubeflow --wait --timeout 10m
KNATIVE_HELM_KEEP_FIXTURE=true ./tests/knative_eventing_helm_smoke_test.sh
helm uninstall knative-eventing -n kubeflow --wait --timeout 10m
[[ $(kubectl get --raw "$ping_path" | python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["uid"])') == "$uid" ]]
[[ $(kubectl get --raw "$eventtype_path" | python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["uid"])') == "$eventtype_uid" ]]
[[ $(kubectl get namespace "$namespace" -o jsonpath='{.metadata.uid}') == "$namespace_uid" ]]
kubectl get -f "$chart/manifests/platform-crds.yaml" >/dev/null
# Retained definitions do not preserve conversion availability after uninstall.
for path in "$converted_ping_path" "$converted_eventtype_path"; do
    if kubectl get --request-timeout=10s --raw "$path" >"$temporary/conversion.out" 2>"$temporary/conversion.err"; then
        echo "Expected unavailable conversion while eventing-webhook is removed" >&2
        exit 1
    fi
    grep -Eiq 'conversion|webhook|service.*not found' "$temporary/conversion.err"
done
./tests/knative_eventing_helm_install.sh
kubectl get --raw "$converted_ping_path" >/dev/null
kubectl get --raw "$converted_eventtype_path" >/dev/null
[[ $(kubectl get --raw "$ping_path" | python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["uid"])') == "$uid" ]]
[[ $(kubectl get --raw "$eventtype_path" | python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["uid"])') == "$eventtype_uid" ]]
KNATIVE_HELM_KEEP_FIXTURE=true ./tests/knative_eventing_helm_smoke_test.sh
echo "Eventing upgrades, rollback, retention, conversion interruption/recovery and fresh delivery passed."
