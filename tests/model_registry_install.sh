#!/bin/bash
set -euxo pipefail

# Install Model Registry server, UI, database, and Istio components
# This script can be used for local testing without GitHub Actions
# Prerequisites: kubeflow-user-example-com namespace must exist (created by Profile controller),
#                kustomize must be installed
# Usage: ./tests/model_registry_install.sh

echo "Installing Model Registry components..."

# Fail fast if the profile namespace has not been provisioned
if ! kubectl get namespace kubeflow-user-example-com >/dev/null 2>&1; then
    echo "ERROR: namespace kubeflow-user-example-com does not exist. Create a Kubeflow Profile first."
    exit 1
fi

# Build and apply Model Registry components (server + database + UI + Istio)
# The overlay sets namespace: kubeflow-user-example-com and patches Istio
# gateway references and destination host FQDNs.
echo "Deploying Model Registry components to kubeflow-user-example-com..."
kustomize build applications/hub/overlays/model-registry \
  | kubectl apply -f -

# Wait for Model Registry database deployment
echo "Waiting for Model Registry database to become ready..."
if ! kubectl wait --for=condition=available -n kubeflow-user-example-com deployment/model-registry-db --timeout=120s; then
    echo "ERROR: Model Registry database deployment failed"
    kubectl get pods -n kubeflow-user-example-com -l component=db
    kubectl describe deployment/model-registry-db -n kubeflow-user-example-com
    kubectl logs deployment/model-registry-db -n kubeflow-user-example-com
    exit 1
fi

# Wait for Model Registry server deployment
echo "Waiting for Model Registry server to become ready..."
if ! kubectl wait --for=condition=available -n kubeflow-user-example-com deployment/model-registry-deployment --timeout=120s; then
    echo "ERROR: Model Registry server deployment failed"
    kubectl get pods -n kubeflow-user-example-com -l component=model-registry-server
    kubectl describe deployment/model-registry-deployment -n kubeflow-user-example-com
    kubectl logs deployment/model-registry-deployment -n kubeflow-user-example-com --all-containers
    exit 1
fi

# Wait for Model Registry UI deployment
echo "Waiting for Model Registry UI to become ready..."
if ! kubectl wait --for=condition=available -n kubeflow-user-example-com deployment/model-registry-ui --timeout=120s; then
    echo "ERROR: Model Registry UI deployment failed"
    kubectl get pods -n kubeflow-user-example-com -l app=model-registry-ui
    kubectl describe deployment/model-registry-ui -n kubeflow-user-example-com
    kubectl logs deployment/model-registry-ui -n kubeflow-user-example-com --all-containers
    exit 1
fi

echo "Model Registry installation complete!"
kubectl get pods -n kubeflow-user-example-com -l component=model-registry-server
kubectl get pods -n kubeflow-user-example-com -l app=model-registry-ui
