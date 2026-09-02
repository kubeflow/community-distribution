#!/bin/bash
set -euo pipefail

echo "Installing Pipelines for ARM64..."

cd applications/pipeline

kubectl apply -f upstream/third-party/metacontroller/base/crd.yaml
kubectl wait --for=condition=established --timeout=30s \
  crd/compositecontrollers.metacontroller.k8s.io

kubectl apply -f upstream/third-party/application/cluster-scoped/application-crd.yaml
kubectl wait --for=condition=established --timeout=30s \
  crd/applications.app.k8s.io

# Keep the synchronized upstream manifests unchanged. The upstream ML Metadata
# image is amd64-only, so override it only in the rendered ARM64 test output.
ARM64_MLMD_IMAGE="ghcr.io/deploykf/ci/ml_metadata_store_server:sha-cad0c56"
kustomize build overlays | \
  sed "s#gcr.io/tfx-oss-public/ml_metadata_store_server:1.14.0#${ARM64_MLMD_IMAGE}#g" | \
  kubectl apply -f -

echo "Waiting for ARM64 KFP deployments..."

for deployment in \
  ml-pipeline \
  ml-pipeline-ui \
  ml-pipeline-persistenceagent \
  ml-pipeline-scheduledworkflow \
  ml-pipeline-viewer-crd \
  cache-server \
  seaweedfs; do
  kubectl wait --for=condition=Available "deployment/${deployment}" \
    -n kubeflow --timeout=600s
done

echo "===== ARM64 PIPELINE DEPLOYMENTS ====="
kubectl get deployments -n kubeflow

echo "===== ARM64 PIPELINE PODS ====="
kubectl get pods -n kubeflow -o wide
