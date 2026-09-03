#!/usr/bin/env bash
# Helm counterpart of tests/notebooks_install.sh, proven equivalent to
# applications/notebooks-v1/overlays/istio by the kubeflow-notebooks scenario.
set -euxo pipefail
echo "Installing Kubeflow Notebooks v1 with Helm ..."
helm install kubeflow-notebooks applications/notebooks-v1/helm \
  --namespace kubeflow \
  --values applications/notebooks-v1/helm/ci/values-platform.yaml \
  --wait --timeout 5m
