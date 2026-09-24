#!/usr/bin/env bash
# Helm counterpart of tests/workspaces_install.sh, proven equivalent to
# applications/workspaces/overlays/istio by the kubeflow-workspaces scenario.
#
# The release record is stored in the kubeflow namespace, which the foundation
# charts create. The chart itself renders Namespace/kubeflow-workspaces.
set -euxo pipefail
echo "Installing Kubeflow Workspaces with Helm ..."

# A kubeflow-workspaces namespace that is still terminating after an earlier
# uninstall would make the installation fail, so wait for it to disappear.
kubectl wait --for=delete namespace/kubeflow-workspaces --timeout=300s

helm install kubeflow-workspaces applications/workspaces/helm \
  --namespace kubeflow \
  --values applications/workspaces/helm/ci/values-istio.yaml \
  --wait --timeout 5m

kubectl wait --for=condition=Ready pods -n kubeflow-workspaces --timeout=300s --all
kubectl wait --for=condition=Available deployment -n kubeflow-workspaces --timeout=300s --all
