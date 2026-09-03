#!/usr/bin/env bash
# Helm counterpart of tests/multi_tenancy_install.sh, proven equivalent to
# common/kubeflow-roles/base by the kubeflow-platform comparison scenario.
set -euxo pipefail
echo "Installing Multitenancy Kubeflow Roles with Helm"
# kubeflow-system already exists: the kubeflow-namespaces chart renders it
# with its labels. Creating it here would mask a broken foundation install.
helm install kubeflow-platform common/kubeflow-roles/helm \
  --namespace kubeflow-system \
  --values common/kubeflow-roles/helm/ci/values-default.yaml \
  --wait --timeout 5m
