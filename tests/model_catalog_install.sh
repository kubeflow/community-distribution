#!/bin/bash
set -euxo pipefail

# Install Model Catalog as a cluster-wide singleton in the kubeflow namespace
# This script can be used for local testing without GitHub Actions
# Prerequisites: kubeflow namespace must exist, kustomize must be installed
# Usage: ./tests/model_catalog_install.sh

echo "Installing Model Catalog components..."

# Fail fast if the kubeflow namespace has not been provisioned
if ! kubectl get namespace kubeflow >/dev/null 2>&1; then
    echo "ERROR: namespace kubeflow does not exist."
    exit 1
fi

# Build and apply Model Catalog components (server + database)
# The overlay sets namespace: kubeflow for cluster-wide singleton deployment.
echo "Deploying Model Catalog components to kubeflow..."
kustomize build applications/hub/overlays/model-catalog \
  | kubectl apply -f -

# Wait for Model Catalog PostgreSQL StatefulSet
echo "Waiting for Model Catalog database to become ready..."
if ! kubectl wait --for=condition=ready -n kubeflow pod \
  -l app.kubernetes.io/name=postgres,app.kubernetes.io/part-of=model-catalog \
  --timeout=120s; then
    echo "ERROR: Model Catalog database pod failed"
    kubectl get pods -n kubeflow -l app.kubernetes.io/part-of=model-catalog || true
    kubectl describe statefulset/model-catalog-postgres -n kubeflow || true
    kubectl logs statefulset/model-catalog-postgres -n kubeflow || true
    exit 1
fi

# Wait for Model Catalog server deployment
echo "Waiting for Model Catalog server to become ready..."
if ! kubectl wait --for=condition=available -n kubeflow deployment/model-catalog-server --timeout=120s; then
    echo "ERROR: Model Catalog server deployment failed"
    kubectl get pods -n kubeflow -l app.kubernetes.io/part-of=model-catalog || true
    kubectl describe deployment/model-catalog-server -n kubeflow || true
    kubectl logs deployment/model-catalog-server -n kubeflow --all-containers || true
    exit 1
fi

echo "Model Catalog installation complete!"
kubectl get pods -n kubeflow -l app.kubernetes.io/part-of=model-catalog
