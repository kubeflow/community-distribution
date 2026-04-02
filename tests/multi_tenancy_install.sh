#!/bin/bash
set -euxo pipefail

echo "Installing Profiles Controller with PSS (Pod Security Standards)"
kustomize build applications/dashboard/upstream/profile-controller/overlays/kubeflow-pss | kubectl apply -f -
kubectl -n kubeflow rollout status deployment/profiles-deployment --timeout 180s
kubectl -n kubeflow wait --for=condition=Ready pods -l app=profile-controller --timeout 180s

echo "Installing Multitenancy Kubeflow Roles"
kustomize build common/kubeflow-roles/base | kubectl apply -f -

