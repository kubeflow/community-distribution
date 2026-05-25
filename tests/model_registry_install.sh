#!/bin/bash
set -euxo pipefail

if ! kubectl get namespace kubeflow-user-example-com >/dev/null 2>&1; then
    echo "ERROR: namespace kubeflow-user-example-com does not exist. Create a Kubeflow Profile first."
    exit 1
fi

kustomize build applications/hub/overlays/model-registry \
  | kubectl apply -f -

# Wait for registry database
if ! kubectl wait --for=condition=available -n kubeflow-user-example-com deployment/model-registry-db --timeout=120s; then
    kubectl get pods -n kubeflow-user-example-com -l component=db
    kubectl describe deployment/model-registry-db -n kubeflow-user-example-com
    kubectl logs deployment/model-registry-db -n kubeflow-user-example-com
    exit 1
fi

# Wait for registry server
if ! kubectl wait --for=condition=available -n kubeflow-user-example-com deployment/model-registry-deployment --timeout=120s; then
    kubectl get pods -n kubeflow-user-example-com -l component=model-registry-server
    kubectl describe deployment/model-registry-deployment -n kubeflow-user-example-com
    kubectl logs deployment/model-registry-deployment -n kubeflow-user-example-com --all-containers
    exit 1
fi

# Wait for registry UI
if ! kubectl wait --for=condition=available -n kubeflow-user-example-com deployment/model-registry-ui --timeout=120s; then
    kubectl get pods -n kubeflow-user-example-com -l app=model-registry-ui
    kubectl describe deployment/model-registry-ui -n kubeflow-user-example-com
    kubectl logs deployment/model-registry-ui -n kubeflow-user-example-com --all-containers
    exit 1
fi

kubectl get pods -n kubeflow-user-example-com -l component=model-registry-server
kubectl get pods -n kubeflow-user-example-com -l app=model-registry-ui
