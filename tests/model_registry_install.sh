#!/bin/bash
set -euxo pipefail

# Install Model Registry server, UI, and database components
# This script can be used for local testing without GitHub Actions
# Usage: ./tests/model_registry_install.sh
#
# Note: Model Catalog (demo overlay) is NOT deployed in CI.
# The demo overlay's perf-data-init container (busybox, UID 0) is incompatible
# with the base deployment's runAsNonRoot: true security context. This is an
# upstream issue. The catalog is an optional demo component not covered by the
# integration tests in model_registry_test.sh, so deploying it in CI adds
# zero test coverage and a known failure mode. It remains in
# example/kustomization.yaml for user installations.

echo "Installing Model Registry components..."

# Build and apply Model Registry server with database
echo "Deploying Model Registry server (with database)..."
kustomize build applications/model-registry/upstream/overlays/postgres \
  | kubectl apply -n kubeflow -f -

# Build and apply Model Registry Istio networking
echo "Deploying Model Registry Istio resources..."
kustomize build applications/model-registry/upstream/options/istio \
  | kubectl apply -n kubeflow -f -

# Build and apply Model Registry UI with Istio integration
echo "Deploying Model Registry UI..."
kustomize build applications/model-registry/upstream/options/ui/overlays/istio \
  | kubectl apply -n kubeflow -f -

# Wait for Model Registry database deployment
echo "Waiting for Model Registry database to become ready..."
if ! kubectl wait --for=condition=available -n kubeflow deployment/model-registry-db --timeout=120s; then
    echo "ERROR: Model Registry database deployment failed"
    kubectl get pods -n kubeflow -l app=model-registry-db
    kubectl describe deployment/model-registry-db -n kubeflow
    kubectl logs deployment/model-registry-db -n kubeflow
    exit 1
fi

# Wait for Model Registry server deployment
echo "Waiting for Model Registry server to become ready..."
if ! kubectl wait --for=condition=available -n kubeflow deployment/model-registry-deployment --timeout=120s; then
    echo "ERROR: Model Registry server deployment failed"
    kubectl get pods -n kubeflow -l component=model-registry-server
    kubectl describe deployment/model-registry-deployment -n kubeflow
    kubectl logs deployment/model-registry-deployment -n kubeflow --all-containers
    exit 1
fi

# Wait for Model Registry UI deployment
echo "Waiting for Model Registry UI to become ready..."
if ! kubectl wait --for=condition=available -n kubeflow deployment/model-registry-ui --timeout=120s; then
    echo "ERROR: Model Registry UI deployment failed"
    kubectl get pods -n kubeflow -l app=model-registry-ui
    kubectl describe deployment/model-registry-ui -n kubeflow
    kubectl logs deployment/model-registry-ui -n kubeflow --all-containers
    exit 1
fi

echo "Model Registry installation complete!"
kubectl get pods -n kubeflow -l component=model-registry-server
kubectl get pods -n kubeflow -l app=model-registry-ui
