#!/bin/bash
set -euxo pipefail

echo "Installing Kubeflow Notebooks v1 ..."

dump_notebooks_debug() {
  kubectl -n kubeflow get deployments,pods -o wide
  kubectl -n kubeflow describe deployments
  kubectl -n kubeflow describe pods
  kubectl -n kubeflow get events --sort-by=.metadata.creationTimestamp
}

wait_for_notebooks_deployment() {
  local deployment=$1

  if ! kubectl -n kubeflow rollout status "deployment/${deployment}" --timeout=180s; then
    dump_notebooks_debug
    return 1
  fi
}

kustomize build applications/notebooks-v1/overlays/istio | kubectl apply -f -

kubectl wait --for=condition=Established --timeout=60s crd/notebooks.kubeflow.org
kubectl wait --for=condition=Established --timeout=60s crd/pvcviewers.kubeflow.org
kubectl wait --for=condition=Established --timeout=60s crd/tensorboards.tensorboard.kubeflow.org
wait_for_notebooks_deployment jupyter-web-app-deployment
wait_for_notebooks_deployment notebook-controller-deployment
wait_for_notebooks_deployment pvcviewer-controller-manager
wait_for_notebooks_deployment tensorboard-controller-deployment
wait_for_notebooks_deployment tensorboards-web-app-deployment
wait_for_notebooks_deployment volumes-web-app-deployment
