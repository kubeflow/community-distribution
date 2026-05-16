#!/bin/bash
set -euxo pipefail

echo "Installing Multitenancy Kubeflow Roles"
kustomize build common/kubeflow-roles/base | kubectl apply -f -
