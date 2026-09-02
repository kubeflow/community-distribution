#!/bin/bash

set -euxo pipefail

NAMESPACE=$1
TIMEOUT=120  # timeout in seconds
SLEEP_INTERVAL=30  # interval between Ray pod deletion checks in seconds
RAY_VERSION=2.56.0

start_time=$(date +%s)
for ((i=0; i<TIMEOUT; i+=2)); do
  if [[ $(kubectl get namespace $NAMESPACE --no-headers 2>/dev/null | wc -l) -eq 1 ]]; then
    echo "Namespace $NAMESPACE created."
    break
  fi
  
  current_time=$(date +%s)
  elapsed_time=$((current_time - start_time))
  
  if [ "$elapsed_time" -ge "$TIMEOUT" ]; then
    echo "Timeout exceeded. Namespace $NAMESPACE not created."
    exit 1
  fi
  
  echo "Waiting for namespace $NAMESPACE to be created..."
  sleep 2
done

echo "Namespace $NAMESPACE has been created!"

kubectl label namespace $NAMESPACE istio-injection=enabled

kubectl get namespaces --selector=istio-injection=enabled

# Install KubeRay operator
kustomize build kuberay-operator/overlays/kubeflow | kubectl -n kubeflow apply --server-side -f -

# Wait for the operator to be ready.
kubectl -n kubeflow wait --for=condition=available --timeout=90s deploy/kuberay-operator
kubectl -n kubeflow get pod -l app.kubernetes.io/component=kuberay-operator

# Install RayCluster components
kubectl -n "$NAMESPACE" apply -f raycluster_example.yaml

if [[ "${GITHUB_ACTIONS:-false}" == "true" ]]; then
  kubectl -n "$NAMESPACE" patch raycluster kubeflow-raycluster --type=merge --patch '{
    "spec": {
      "autoscalerOptions": {
        "securityContext": {
          "allowPrivilegeEscalation": false,
          "capabilities": {"drop": ["ALL"]},
          "runAsNonRoot": true,
          "seccompProfile": {"type": "RuntimeDefault"}
        }
      }
    }
  }'
  kubectl -n "$NAMESPACE" get raycluster kubeflow-raycluster -o jsonpath='{.spec.autoscalerOptions.securityContext.seccompProfile.type}' | grep -qx RuntimeDefault
fi

# Wait for the RayCluster to be ready.
sleep 5
kubectl -n $NAMESPACE wait --for=condition=Ready pod -l ray.io/cluster=kubeflow-raycluster --timeout=90s
kubectl -n $NAMESPACE logs -l ray.io/cluster=kubeflow-raycluster,ray.io/node-type=head

# Forward the port of Dashboard
sleep 5
kubectl -n $NAMESPACE port-forward --address 0.0.0.0 svc/kubeflow-raycluster-head-svc 8265:8265 &
PID=$!
echo "Forward the port 8265 of Ray head in the background process: $PID"

# Send a curl command to test basic Ray functionality.
sleep 5
output=$(curl -H "Content-Type: application/json" localhost:8265/api/version)
echo "output: ${output}"

# output format: {"version": ..., "ray_version": RAY_VERSION, "ray_commit": ...}
if echo "${output}" | grep -q $RAY_VERSION; then
  echo "Test succeeded!"
else
  echo "Test failed!"
  exit 1
fi

# Delete RayCluster
kubectl -n $NAMESPACE delete -f raycluster_example.yaml

# Wait for all Ray Pods to be deleted.
start_time=$(date +%s)
for ((i=0; i<TIMEOUT; i+=SLEEP_INTERVAL)); do
  pods=$(kubectl -n $NAMESPACE get pods -o json | jq '.items | length')
  if [ "$pods" -eq 0 ]; then
    kill $PID
    break
  fi
  current_time=$(date +%s)
  elapsed_time=$((current_time - start_time))
  if [ "$elapsed_time" -ge "$TIMEOUT" ]; then
    echo "Timeout exceeded. Exiting loop."
    exit 1
  fi
  sleep $SLEEP_INTERVAL
done

# Delete KubeRay operator
kustomize build kuberay-operator/base | kubectl -n kubeflow delete -f -
