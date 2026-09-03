#!/usr/bin/env bash
# Helm counterpart of tests/katib_install.sh, proven equivalent to
# applications/katib/upstream/installs/katib-with-kubeflow by the katib
# with-kubeflow comparison scenario.
set -euxo pipefail
helm install katib experimental/helm/charts/katib \
  --namespace kubeflow \
  --values experimental/helm/charts/katib/ci/values-kubeflow.yaml \
  --wait --timeout 5m
kubectl wait --for=condition=Available deployment/katib-controller -n kubeflow --timeout=300s
kubectl wait --for=condition=Available deployment/katib-mysql -n kubeflow --timeout=300s
kubectl label namespace $KF_PROFILE katib.kubeflow.org/metrics-collector-injection=enabled --overwrite
