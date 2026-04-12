#!/usr/bin/env bash
set -euo pipefail

# Track port-forward process IDs so they are always killed on exit.
PORT_FORWARD_PIDS=()

cleanup() {
  echo "Cleaning up port-forwarding processes..."
  for pid in "${PORT_FORWARD_PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}

trap cleanup EXIT

wait_or_dump() {
  local ns="$1"
  local deploy="$2"
  local timeout="${3:-60s}"

  if ! kubectl wait --for=condition=available -n "$ns" "deployment/$deploy" --timeout="$timeout"; then
    echo "ERROR: deployment $deploy in namespace $ns did not become available"
    kubectl get events -n "$ns" --sort-by='.lastTimestamp' || true
    kubectl describe "deployment/$deploy" -n "$ns" || true
    kubectl logs "deployment/$deploy" -n "$ns" --all-containers --tail=50 || true
    exit 1
  fi
}

wait_for_port() {
  local port="$1"
  local pid="$2"
  local max_retries="${3:-30}"
  local count=0

  while ! curl -s "localhost:$port" > /dev/null; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "ERROR: Port-forward process (PID $pid) for port $port died"
      return 1
    fi
    if [ "$count" -ge "$max_retries" ]; then
      echo "ERROR: Timeout waiting for port-forwarding $port"
      return 1
    fi
    echo "waiting for port-forwarding $port..."
    sleep 1
    count=$((count+1))
  done
  echo "port-forwarding $port ready"
}

echo "Waiting for all Model Registry Pods to become ready..."
wait_or_dump kubeflow model-registry-db
wait_or_dump kubeflow model-registry-deployment
wait_or_dump kubeflow model-registry-ui

echo "Dry-run KF Model Registry API directly..."
nohup kubectl port-forward svc/model-registry-service -n kubeflow 8081:8080 &
PORT_FORWARD_PID_8081=$!
PORT_FORWARD_PIDS+=($PORT_FORWARD_PID_8081)

if ! wait_for_port 8081 "$PORT_FORWARD_PID_8081"; then
  exit 1
fi

curl -v -X 'GET' \
  'http://localhost:8081/api/model_registry/v1alpha3/registered_models?pageSize=100&orderBy=ID&sortOrder=DESC' \
  -H 'accept: application/json'

if ! lsof -i:8080 -t >/dev/null; then
  echo "Port 8080 not in use, starting Istio gateway port-forward..."
  INGRESS_GATEWAY_SERVICE=$(kubectl get svc --namespace istio-system --selector="app=istio-ingressgateway" --output jsonpath='{.items[0].metadata.name}')
  nohup kubectl port-forward --namespace istio-system svc/${INGRESS_GATEWAY_SERVICE} 8080:80 &
  PORT_FORWARD_PID_8080=$!
  PORT_FORWARD_PIDS+=($PORT_FORWARD_PID_8080)

  if ! wait_for_port 8080 "$PORT_FORWARD_PID_8080"; then
    exit 1
  fi
fi

echo "Dry-run KF Model Registry REST API..."
export KF_TOKEN="$(kubectl -n default create token default)"
curl -v -H "Authorization: Bearer ${KF_TOKEN}" http://localhost:8080/api/model_registry/v1alpha3/registered_models

echo "Dry-run KF Model Registry REST API UI..."
export KF_PROFILE=kubeflow-user-example-com
export KF_TOKEN="$(kubectl -n ${KF_PROFILE} create token default-editor)"

STATUS_CODE=$(curl -v \
    --silent --output /dev/stderr --write-out "%{http_code}" \
    "localhost:8080/model-registry/api/v1/model_registry?namespace=${KF_PROFILE}" \
    -H "Authorization: Bearer ${KF_TOKEN}")

if [[ "$STATUS_CODE" -ne 200 ]]; then
    echo "Error, this call should be authorized to list model registries in namespace ${KF_PROFILE}."
    exit 1
fi

echo "Dry-run KF Model Registry REST API UI with unauthorized SA Token..."
export KF_TOKEN_UNAUTH="$(kubectl -n default create token default)"

STATUS_CODE_UNAUTH=$(curl -v \
    --silent --output /dev/stderr --write-out "%{http_code}" \
    "localhost:8080/model-registry/api/v1/model_registry?namespace=${KF_PROFILE}" \
    -H "Authorization: Bearer ${KF_TOKEN_UNAUTH}")

if [[ "$STATUS_CODE_UNAUTH" -ne 403 ]]; then
    echo "Error, this call should fail to list model registry resources in namespace ${KF_PROFILE}."
    exit 1
fi

echo "Model Registry tests completed successfully."
