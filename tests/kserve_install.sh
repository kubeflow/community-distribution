#!/bin/bash
set -euxo pipefail
echo "Installing Kserve ..."
cd applications/kserve
kustomize build kserve | kubectl apply --server-side --force-conflicts -f - || true
kubectl wait --for=condition=Ready pods --all --all-namespaces --timeout=60s --field-selector=status.phase!=Succeeded
kubectl wait --for=condition=Ready -n kserve --timeout=60s \
  certificate/serving-cert \
  certificate/llmisvc-serving-cert \
  certificate/localmodel-serving-cert
kubectl wait --for=create -n kserve --timeout=60s \
  secret/kserve-webhook-server-cert \
  secret/llmisvc-webhook-server-cert \
  secret/localmodel-webhook-server-cert

kubectl wait --for condition=established --timeout=30s crd/clusterservingruntimes.serving.kserve.io
kustomize build kserve | kubectl apply --server-side --force-conflicts -f -

kustomize build kserve-ui | kubectl apply --server-side --force-conflicts -f -
kubectl wait --for=condition=Ready pods --all --all-namespaces --timeout=600s \
  --field-selector=status.phase!=Succeeded
kubectl wait --for=condition=Available -n kserve --timeout=120s \
  deployment/kserve-controller-manager \
  deployment/kserve-localmodel-controller-manager \
  deployment/llmisvc-controller-manager \
  deployment/kserve-models-web-application
kubectl get deployment -n kserve -l control-plane
kubectl get deployment/kserve-models-web-application -n kserve
kubectl get crd | grep -E 'inferenceservice|servingruntimes'

# Return to the original directory
cd ../../
