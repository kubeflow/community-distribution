#!/usr/bin/env bash
# Without an argument: destructive Eventing release lifecycle. Run it only on a
# disposable cluster that no later test needs; the knative_eventing_helm_lifecycle
# job in .github/workflows/knative_test.yaml does. With --smoke-only: one fresh
# PingSource delivery and no Helm operation, for the full Helm integration job.
set -euo pipefail
smoke_only=false
evidence=logs/knative-eventing-lifecycle
case "$#:${1:-}" in
    0:) ;;
    1:--smoke-only)
        smoke_only=true
        evidence=logs/knative-eventing-smoke
        ;;
    *)
        echo "Usage: knative_eventing_helm_lifecycle_test.sh [--smoke-only]" >&2
        exit 2
        ;;
esac
chart=common/knative/knative-eventing/helm
namespace=knative-eventing
fixture=knative-helm-events
temporary=$(mktemp -d)
capture_diagnostics() {
    local directory="$evidence/$1"
    mkdir -p "$directory" || return 0
    kubectl get deployments,pods,events -n "$namespace" --request-timeout=10s -o yaml >"$directory/resources.yaml" 2>&1 || true
    for deployment in eventing-controller eventing-webhook pingsource-mt-adapter "$fixture"; do
        kubectl logs "deployment/$deployment" -n "$namespace" --request-timeout=10s --tail=100 >"$directory/$deployment.log" 2>&1 || true
    done
}
cleanup() {
    local status=$?
    rm -rf "$temporary"
    if (( status != 0 )); then
        capture_diagnostics failure
        echo "Preserving Eventing fixtures after failure; see $evidence/." >&2
    else
        kubectl delete pingsource,eventtype,service,deployment "$fixture" -n "$namespace" --ignore-not-found || status=$?
    fi
    exit "$status"
}
trap cleanup EXIT
# Create the receiver and retained PingSource once for the whole lifecycle.
kubectl apply -n "$namespace" -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $fixture
spec:
  replicas: 1
  selector:
    matchLabels: {helm-test: $fixture}
  template:
    metadata:
      labels: {helm-test: $fixture}
      annotations:
        sidecar.istio.io/inject: "false"
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 65532
        seccompProfile: {type: RuntimeDefault}
      containers:
      - name: receiver
        image: python:3.12-alpine
        command: [python3, -u, -c]
        args:
        - |
          import http.server, json
          class Receiver(http.server.BaseHTTPRequestHandler):
              def do_POST(self):
                  body = self.rfile.read(int(self.headers['Content-Length']))
                  print(json.dumps({'type': self.headers.get('Ce-Type'), 'data': body.decode()}), flush=True)
                  self.send_response(204)
                  self.end_headers()
          http.server.HTTPServer(('0.0.0.0', 8080), Receiver).serve_forever()
        ports:
        - containerPort: 8080
        resources:
          requests: {cpu: 50m, memory: 32Mi}
          limits: {cpu: 200m, memory: 128Mi}
        securityContext:
          allowPrivilegeEscalation: false
          capabilities:
            drop: [ALL]
---
apiVersion: v1
kind: Service
metadata:
  name: $fixture
spec:
  selector: {helm-test: $fixture}
  ports:
  - port: 80
    targetPort: 8080
---
apiVersion: sources.knative.dev/v1
kind: PingSource
metadata:
  name: $fixture
spec:
  schedule: "* * * * *"
  contentType: application/json
  data: '{"message":"knative-helm-event-ok"}'
  sink:
    ref:
      apiVersion: v1
      kind: Service
      name: $fixture
EOF
kubectl rollout status "deployment/$fixture" -n "$namespace" --timeout=120s
kubectl wait --for=condition=Ready "pingsource/$fixture" -n "$namespace" --timeout=180s
check_event_delivery() {
    # Use only logs since this invocation, so replay cannot pass on old delivery.
    local started
    started=$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)
    local delivered=false attempt
    for ((attempt=0; attempt<75; attempt++)); do
        if kubectl logs "deployment/$fixture" -n "$namespace" --since-time="$started" | \
            python3 -c 'import json,sys
count=0
for line in sys.stdin:
    try:
        event=json.loads(line)
        count += event.get("type")=="dev.knative.sources.ping" and json.loads(event.get("data", "null"))=={"message":"knative-helm-event-ok"}
    except (ValueError, TypeError, AttributeError):
        pass
print("Matching newly delivered CloudEvents:", count)
sys.exit(count < 1)'; then
            delivered=true
            break
        fi
        sleep 2
    done
    if [[ "$delivered" != true ]]; then
        echo "No matching fresh PingSource CloudEvent arrived within 150 seconds" >&2
        exit 1
    fi
    echo "Eventing delivered the exact PingSource CloudEvent payload."
}
check_event_delivery
if [[ "$smoke_only" == true ]]; then
    echo "Eventing smoke passed: fresh PingSource delivery only; no Helm lifecycle operation ran."
    exit 0
fi
mkdir -p "$evidence"
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
controller_annotation() {
    kubectl get deployment/eventing-controller -n "$namespace" \
        -o jsonpath='{.spec.template.metadata.annotations.tests\.kubeflow\.org/lifecycle}'
}
# Snapshots stay under the uploaded evidence directory, one file per phase.
capture_adapter >"$evidence/adapter-before-upgrades.txt"
capture_diagnostics before-upgrades
for attempt in 1 2; do
    helm upgrade knative-eventing "$chart" -n kubeflow --reset-values --set installation.phase=complete --wait --timeout 10m
    # A new event gives the adapter time to process work after each upgrade.
    check_event_delivery
    capture_adapter >"$evidence/adapter-after-unchanged-upgrade-$attempt.txt"
    if ! diff -u "$evidence/adapter-before-upgrades.txt" "$evidence/adapter-after-unchanged-upgrade-$attempt.txt"; then
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
capture_diagnostics before-changed-upgrade
helm upgrade knative-eventing "$temporary/chart" -n kubeflow --wait --timeout 10m
kubectl rollout status deployment/eventing-controller -n "$namespace" --timeout=120s
# A standalone assignment lets a failed read stop the script.
changed_annotation=$(controller_annotation)
if [[ "$changed_annotation" != changed ]]; then
    echo "The changed upgrade did not reach the live eventing-controller Pod template" >&2
    exit 1
fi
check_event_delivery
capture_diagnostics before-rollback
helm rollback knative-eventing "$revision" -n kubeflow --wait --timeout 10m
kubectl rollout status deployment/eventing-controller -n "$namespace" --timeout=120s
restored_annotation=$(controller_annotation)
if [[ -n "$restored_annotation" ]]; then
    echo "Rollback did not restore the live eventing-controller Pod template" >&2
    exit 1
fi
check_event_delivery
capture_diagnostics before-uninstall
helm uninstall knative-eventing -n kubeflow --wait --timeout 10m
[[ $(kubectl get --raw "$ping_path" | python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["uid"])') == "$uid" ]]
[[ $(kubectl get --raw "$eventtype_path" | python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["uid"])') == "$eventtype_uid" ]]
[[ $(kubectl get namespace "$namespace" -o jsonpath='{.metadata.uid}') == "$namespace_uid" ]]
kubectl get -f "$chart/manifests/platform-crds.yaml" >/dev/null
# Retained definitions do not preserve conversion availability after uninstall.
for path in "$converted_ping_path" "$converted_eventtype_path"; do
    conversion="$evidence/conversion-after-uninstall-$(basename "${path%/*}")"
    if kubectl get --request-timeout=10s --raw "$path" >"$conversion.out" 2>"$conversion.err"; then
        echo "Expected unavailable conversion while eventing-webhook is removed" >&2
        exit 1
    fi
    grep -Eiq 'conversion|webhook|service.*not found' "$conversion.err"
done
./tests/knative_eventing_helm_install.sh
# Pod readiness does not verify the API server's trust of the new webhook
# certificate. Wait for real conversions of both retained objects to recover.
for path in "$converted_ping_path" "$converted_eventtype_path"; do
    deadline=$((SECONDS + 120))
    until kubectl get --request-timeout=10s --raw "$path" >/dev/null; do
        if (( SECONDS >= deadline )); then
            echo "Conversion did not recover within 120 seconds: $path" >&2
            exit 1
        fi
        sleep 2
    done
done
[[ $(kubectl get --raw "$ping_path" | python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["uid"])') == "$uid" ]]
[[ $(kubectl get --raw "$eventtype_path" | python3 -c 'import json,sys; print(json.load(sys.stdin)["metadata"]["uid"])') == "$eventtype_uid" ]]
check_event_delivery
echo "Eventing lifecycle passed: unchanged upgrades, live changed upgrade and rollback, retention, conversion interruption/recovery and fresh delivery."
