#!/bin/bash
set -euo pipefail

kustomize build applications/training-operator/overlays/kubeflow-restricted-pss | kubectl apply --server-side --force-conflicts -f -

kubectl wait --for=condition=Available deployment/training-operator -n kubeflow --timeout=180s
kubectl get deployment -n kubeflow training-operator
kubectl get pods -n kubeflow -l app=training-operator
kubectl get crd | grep -E 'tfjobs.kubeflow.org|pytorchjobs.kubeflow.org'
