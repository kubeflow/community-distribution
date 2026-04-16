#!/bin/bash
set -euxo pipefail

echo "Installing Kubeflow Workspaces ..."

kustomize build applications/workspaces/overlays/istio | kubectl apply -f -

kubectl wait --for=condition=Ready pods -n cert-manager --all --timeout=120s
kubectl wait --for=condition=Ready pods \
  -n kubeflow-workspaces --all \
  --timeout=600s

kubectl rollout status deployment/workspaces-controller -n kubeflow-workspaces
kubectl rollout status deployment/workspaces-backend -n kubeflow-workspaces
kubectl rollout status deployment/workspaces-frontend -n kubeflow-workspaces
