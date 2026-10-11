#!/usr/bin/env bash
# Real Knative Service routing, including JWT rejection at the cluster-local gateway.
set -euo pipefail
namespace=${1:?Usage: knative_serving_helm_smoke_test.sh PROFILE_NAMESPACE}
fixture=knative-helm-routing
port=${KNATIVE_HELM_TEST_PORT:-18081}
port_forward_pid=""
cleanup() {
    local status=$?
    if [[ -n "$port_forward_pid" ]]; then kill "$port_forward_pid" 2>/dev/null || true; fi
    if (( status != 0 )); then
        echo "Preserving the Knative Serving fixture after failure." >&2
    elif [[ "${KNATIVE_HELM_KEEP_FIXTURE:-false}" != true ]]; then
        kubectl delete services.serving.knative.dev "$fixture" -n "$namespace" --ignore-not-found || status=$?
        kubectl delete authorizationpolicy "$fixture" -n "$namespace" --ignore-not-found || status=$?
    fi
    exit "$status"
}
trap cleanup EXIT
kubectl apply -n "$namespace" -f - <<EOF
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: $fixture
  labels:
    networking.knative.dev/visibility: cluster-local
spec:
  template:
    metadata:
      labels:
        helm-test: $fixture
      annotations:
        autoscaling.knative.dev/min-scale: "1"
    spec:
      containers:
      - image: hashicorp/http-echo:1.0.0
        args: ["-listen=:8080", "-text=knative-helm-routing-ok"]
        ports:
        - containerPort: 8080
        resources:
          requests: {cpu: 50m, memory: 32Mi}
          limits: {cpu: 200m, memory: 64Mi}
        securityContext:
          runAsNonRoot: true
          runAsUser: 65532
          seccompProfile:
            type: RuntimeDefault
          allowPrivilegeEscalation: false
          capabilities:
            drop: [ALL]
---
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: $fixture
spec:
  selector:
    matchLabels:
      helm-test: $fixture
  action: ALLOW
  rules:
  - {}
EOF
kubectl wait --for=condition=Ready "services.serving.knative.dev/$fixture" -n "$namespace" --timeout=300s
hostname=$(kubectl get "services.serving.knative.dev/$fixture" -n "$namespace" -o jsonpath='{.status.url}')
hostname=${hostname#http://}
hostname=${hostname#https://}
token=$(kubectl create token default-editor -n "$namespace")
kubectl port-forward -n istio-system service/knative-local-gateway "$port:80" >/dev/null 2>&1 &
port_forward_pid=$!
# Retry only transport/route readiness; every successful response must be the fixture body.
response=""
for ((attempt=0; attempt<30; attempt++)); do
    response=$(curl --silent --show-error --max-time 5 --fail \
        -H "Host: $hostname" -H "Authorization: Bearer $token" "http://localhost:$port/" || true)
    if [[ "$response" == "knative-helm-routing-ok" ]]; then break; fi
    sleep 2
done
if [[ "$response" != "knative-helm-routing-ok" ]]; then
    echo "Expected the fixture body from the Knative route, received: $response" >&2
    exit 1
fi
status=$(curl --silent --max-time 5 --output /dev/null --write-out '%{http_code}' \
    -H "Host: $hostname" "http://localhost:$port/")
if [[ "$status" != 403 ]]; then
    echo "Expected HTTP 403 without a JWT, received: $status" >&2
    exit 1
fi
echo "Knative Serving routed the exact fixture body and rejected a missing JWT."
