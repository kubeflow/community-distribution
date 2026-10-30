#!/bin/bash
set -euo pipefail

profile_namespace=${1:-kubeflow-user-example-com}
gateway_endpoint=${GATEWAY_ENDPOINT:-http://localhost:8080}
registry_endpoint="http://model-registry-service.${profile_namespace}.svc.cluster.local:8080/api/model_registry/v1alpha3/registered_models"
ui_route="${gateway_endpoint}/model-registry/api/v1/model_registry/model-registry-service/registered_models?namespace=${profile_namespace}"
response_file=$(mktemp)
control_probe="registry-egress-control-${RANDOM}"

kustomize build applications/hub/upstream/options/ui/overlays/istio | kubectl apply -f -
kubectl -n "$profile_namespace" delete virtualservice model-registry-ui --ignore-not-found
kubectl -n kubeflow rollout status deployment/model-registry-ui --timeout=180s

kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${control_probe}
  namespace: kubeflow
  labels:
    app: registry-egress-control
spec:
  restartPolicy: Never
  serviceAccountName: default
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
  - name: registry-egress-probe
    image: busybox:1.37.0
    command: ["sleep", "900"]
    resources:
      requests:
        cpu: 10m
        memory: 16Mi
      limits:
        memory: 64Mi
    securityContext:
      allowPrivilegeEscalation: false
      capabilities:
        drop: ["ALL"]
EOF
kubectl -n kubeflow wait --for=condition=Ready "pod/$control_probe" --timeout=180s

profile_token=$(kubectl -n "$profile_namespace" create token default-editor --duration=10m)
unauthorized_token=$(kubectl -n default create token default --duration=10m)

assert_ui_response() {
    local expected_status=$1
    local token=$2
    local deadline=$((SECONDS + 90))
    local status
    while true; do
        status=$(curl --silent --show-error --max-time 20 \
            -o "$response_file" -w '%{http_code}' \
            -H "Authorization: Bearer $token" "$ui_route")
        if [[ $status == "$expected_status" ]]; then
            break
        fi
        if (( SECONDS >= deadline )); then
            printf 'FAIL: shared UI expected HTTP %s, received %s\n' "$expected_status" "$status" >&2
            return 1
        fi
        sleep 2
    done
    if [[ $expected_status == 200 ]]; then
        python -c 'import json, sys; data = json.load(open(sys.argv[1])); assert any(item["name"] == "test-model" for item in data["data"]["items"])' "$response_file"
    elif [[ $expected_status == 403 ]]; then
        python -c 'import json, sys; error = json.load(open(sys.argv[1]))["error"]; assert error == {"code": "403", "message": "Access forbidden"}' "$response_file"
    fi
    printf 'PASS: real shared UI returned HTTP %s\n' "$status"
}

assert_probe_denied() {
    local namespace=$1
    local probe=$2
    local endpoint=$3
    local response
    response=$(kubectl -n "$namespace" exec "$probe" -c registry-egress-probe -- \
        wget -S -O /dev/null -T 20 --header='kubeflow-userid: user@example.com' "$endpoint" 2>&1) || true
    grep -Eq 'HTTP/1[.][01] 403 ' <<< "$response" || {
        printf 'FAIL: unrelated workload %s/%s did not receive HTTP 403\n' "$namespace" "$probe" >&2
        return 1
    }
    printf 'PASS: unrelated workload %s/%s denied with HTTP 403\n' "$namespace" "$probe"
}

assert_ui_response 200 "$profile_token"
assert_ui_response 403 "$unauthorized_token"
status=$(curl --silent --show-error --max-time 20 -o /dev/null -w '%{http_code}' "$ui_route")
[[ $status == 302 || $status == 401 || $status == 403 ]] || {
    printf 'FAIL: unauthenticated UI request returned HTTP %s\n' "$status" >&2
    exit 1
}
printf 'PASS: unauthenticated gateway request denied with HTTP %s\n' "$status"
assert_probe_denied kubeflow "$control_probe" "$registry_endpoint"
assert_probe_denied kubeflow "$control_probe" "http://model-registry-ui-service.kubeflow.svc.cluster.local/api/v1/model_registry?namespace=${profile_namespace}"

printf 'Shared Registry UI cross-namespace authentication and authorization checks passed.\n'
