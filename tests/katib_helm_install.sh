#!/usr/bin/env bash
# Helm counterpart of tests/katib_install.sh, proven equivalent to
# applications/katib/upstream/installs/katib-with-kubeflow by the katib
# platform comparison scenario.
set -euxo pipefail
helm install katib applications/katib/helm \
  --namespace kubeflow \
  --values applications/katib/helm/ci/values-platform.yaml \
  --wait --timeout 5m
kubectl wait --for=condition=Available deployment/katib-controller -n kubeflow --timeout=300s
kubectl wait --for=condition=Available deployment/katib-mysql -n kubeflow --timeout=300s
kubectl label namespace $KF_PROFILE katib.kubeflow.org/metrics-collector-injection=enabled --overwrite
