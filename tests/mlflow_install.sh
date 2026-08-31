#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(dirname "$SCRIPT_DIRECTORY")"

echo "Installing MLflow..."
kustomize build "$REPOSITORY_ROOT/applications/mlflow/overlays/kubeflow" \
  | kubectl apply --server-side --force-conflicts -f -

kubectl wait --for=condition=Available deployment/mlflow \
  --namespace kubeflow \
  --timeout=300s

kubectl get deployment,service,persistentvolumeclaim \
  --namespace kubeflow \
  --selector app.kubernetes.io/name=mlflow
