#!/bin/bash
set -euxo pipefail

echo "Installing Kubeflow Workspaces ..."

kustomize build applications/workspaces/overlays/istio | kubectl apply -f -

kubectl wait --for=condition=Ready pods -n kubeflow-workspaces --timeout=300s --all
kubectl wait --for=condition=Available deployment -n kubeflow-workspaces --timeout=300s --all
