#!/usr/bin/env bash
# Helm counterpart of tests/dashboard_install.sh, proven equivalent to
# applications/dashboard/overlays/istio by the kubeflow-dashboard scenario.
set -euxo pipefail
echo "Installing Kubeflow Dashboard with Helm ..."
helm install kubeflow-dashboard applications/dashboard/helm \
  --namespace kubeflow \
  --values applications/dashboard/helm/ci/values-platform.yaml \
  --wait --timeout 5m
kubectl wait --for=condition=Established --timeout=60s crd/profiles.kubeflow.org
kubectl wait --for=condition=Established --timeout=60s crd/poddefaults.kubeflow.org
kubectl wait --for=condition=Ready pods -n kubeflow -l app.kubernetes.io/part-of=kubeflow-dashboard --timeout=60s
