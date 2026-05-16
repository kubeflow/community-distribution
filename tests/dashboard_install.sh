#!/bin/bash
set -euxo pipefail

echo "Installing Kubeflow Dashboard ..."

kustomize build applications/dashboard/overlays/istio | kubectl apply -f -

kubectl -n kubeflow rollout status deployment/dashboard --timeout=60s
kubectl -n kubeflow rollout status deployment/poddefaults-webhook-deployment --timeout=60s
kubectl -n kubeflow rollout status deployment/profiles-deployment --timeout=60s
kubectl wait --for=condition=Established --timeout=60s crd/profiles.kubeflow.org
kubectl wait --for=condition=Established --timeout=60s crd/poddefaults.kubeflow.org
kubectl wait --for=condition=Ready pods -n kubeflow -l app.kubernetes.io/part-of=kubeflow-dashboard --timeout=60s
