#!/bin/bash
set -euxo pipefail

kustomize build applications/hub/overlays/model-catalog \
  | kubectl apply -f -

# Wait for catalog database
if ! kubectl wait --for=condition=ready -n kubeflow pod \
  -l app.kubernetes.io/name=postgres,app.kubernetes.io/part-of=model-catalog \
  --timeout=120s; then
    kubectl get pods -n kubeflow -l app.kubernetes.io/part-of=model-catalog
    kubectl describe statefulset/model-catalog-postgres -n kubeflow
    kubectl logs statefulset/model-catalog-postgres -n kubeflow
    exit 1
fi

# Wait for catalog server
if ! kubectl wait --for=condition=available -n kubeflow deployment/model-catalog-server --timeout=120s; then
    kubectl get pods -n kubeflow -l app.kubernetes.io/part-of=model-catalog
    kubectl describe deployment/model-catalog-server -n kubeflow
    kubectl logs deployment/model-catalog-server -n kubeflow --all-containers
    exit 1
fi

kubectl get pods -n kubeflow -l app.kubernetes.io/part-of=model-catalog
