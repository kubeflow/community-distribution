#!/bin/bash
set -euxo pipefail

cd applications/katib && kustomize build overlays/katib-with-kubeflow | kubectl apply -f - && cd ../../

kubectl wait --for=condition=Available deployment/katib-controller -n kubeflow --timeout=300s

kubectl wait --for=condition=Available deployment/katib-mysql -n kubeflow --timeout=300s

kubectl label namespace $KF_PROFILE katib.kubeflow.org/metrics-collector-injection=enabled --overwrite
