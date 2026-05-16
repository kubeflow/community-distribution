#!/bin/bash
set -euxo pipefail

echo "Installing Kubeflow Notebooks v1 ..."

kustomize build applications/notebooks-v1/overlays/istio | kubectl apply -f -

kubectl wait --for=condition=Established --timeout=60s crd/notebooks.kubeflow.org
kubectl wait --for=condition=Established --timeout=60s crd/pvcviewers.kubeflow.org
kubectl wait --for=condition=Established --timeout=60s crd/tensorboards.tensorboard.kubeflow.org
kubectl -n kubeflow rollout status deployment/jupyter-web-app-deployment --timeout=60s
kubectl -n kubeflow rollout status deployment/notebook-controller-deployment --timeout=60s
kubectl -n kubeflow rollout status deployment/pvcviewer-controller-manager --timeout=60s
kubectl -n kubeflow rollout status deployment/tensorboard-controller-deployment --timeout=60s
kubectl -n kubeflow rollout status deployment/tensorboards-web-app-deployment --timeout=60s
kubectl -n kubeflow rollout status deployment/volumes-web-app-deployment --timeout=60s
