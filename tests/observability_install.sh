#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

echo "Applying observability stack (server-side)..."
kustomize build common/observability/overlays/kubeflow \
  | kubectl apply --server-side --force-conflicts -f -

echo "Waiting for Prometheus Operator to be ready..."
kubectl wait --for=condition=Available deployment \
  -l app.kubernetes.io/name=prometheus-operator \
  -n kubeflow-monitoring-system \
  --timeout=180s

echo "Waiting for Grafana Operator to be ready..."
kubectl wait --for=condition=Available deployment \
  -l control-plane=controller-manager \
  -n kubeflow-monitoring-system \
  --timeout=180s

echo "Observability stack installed successfully."
