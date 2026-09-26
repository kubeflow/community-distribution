#!/bin/bash
set -euxo pipefail

if [[ "${GITHUB_ACTIONS:-false}" == "true" ]]; then
  kustomize build applications/katib/overlays/security | kubectl apply -f -
else
  kustomize build applications/katib/upstream/installs/katib-with-kubeflow | kubectl apply -f -
fi

kubectl rollout status deployment/katib-controller -n kubeflow --timeout=300s
kubectl wait --for=condition=Available deployment/katib-controller -n kubeflow --timeout=300s

kubectl wait --for=condition=Available deployment/katib-mysql -n kubeflow --timeout=300s

kubectl label namespace $KF_PROFILE katib.kubeflow.org/metrics-collector-injection=enabled --overwrite
