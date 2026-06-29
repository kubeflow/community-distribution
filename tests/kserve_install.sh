#!/bin/bash
set -euxo pipefail
echo "Installing Kserve ..."
cd applications/kserve
kustomize build kserve | kubectl apply --server-side --force-conflicts -f - || true
kubectl wait --for=condition=Ready pods --all --all-namespaces --timeout=60s --field-selector=status.phase!=Succeeded
kubectl wait --for=condition=Ready certificate/serving-cert -n kubeflow --timeout=60s
kubectl wait --for=create secret/kserve-webhook-server-cert -n kubeflow --timeout=60s

kubectl wait --for condition=established --timeout=30s crd/clusterservingruntimes.serving.kserve.io
kustomize build kserve | kubectl apply --server-side --force-conflicts -f -

kustomize build models-web-app/upstream/overlays/kubeflow | kubectl apply --server-side --force-conflicts -f -
kubectl wait --for=condition=Ready pods --all --all-namespaces --timeout=600s \
  --field-selector=status.phase!=Succeeded
kubectl wait --for=condition=Available deployment/kserve-controller-manager -n kubeflow --timeout=10s
kubectl wait --for=condition=Available deployment/kserve-models-web-application -n kubeflow --timeout=10s
kubectl get deployment -n kubeflow -l app.kubernetes.io/name=kserve
kubectl get crd | grep -E 'inferenceservice|servingruntimes'

# Return to the original directory
cd ../../
