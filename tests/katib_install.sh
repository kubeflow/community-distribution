#!/bin/bash
set -euxo pipefail

kustomize build applications/katib/overlays/security | kubectl apply -f -
kubectl rollout status deployment/katib-controller -n kubeflow --timeout=300s
kubectl wait --for=condition=Available deployment/katib-controller -n kubeflow --timeout=300s

kubectl wait --for=condition=Available deployment/katib-mysql -n kubeflow --timeout=300s

kubectl label namespace $KF_PROFILE katib.kubeflow.org/metrics-collector-injection=enabled --overwrite
