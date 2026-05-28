#!/bin/bash
set -euxo pipefail

echo "Installing Kubeflow Dashboard ..."

dump_dashboard_debug() {
  kubectl -n kubeflow get deployment,pods -l app.kubernetes.io/part-of=kubeflow-dashboard -o wide
  kubectl -n kubeflow describe deployment/dashboard
  kubectl -n kubeflow describe pods -l app=dashboard
  kubectl -n kubeflow get events --sort-by=.metadata.creationTimestamp
}

kustomize build applications/dashboard/overlays/istio | kubectl apply -f -

kubectl -n kubeflow rollout status deployment/dashboard --timeout=180s || (
  dump_dashboard_debug
  exit 1
)
kubectl -n kubeflow rollout status deployment/poddefaults-webhook-deployment --timeout=180s || (
  dump_dashboard_debug
  exit 1
)
kubectl -n kubeflow rollout status deployment/profiles-deployment --timeout=180s || (
  dump_dashboard_debug
  exit 1
)
kubectl wait --for=condition=Established --timeout=60s crd/profiles.kubeflow.org
kubectl wait --for=condition=Established --timeout=60s crd/poddefaults.kubeflow.org
kubectl wait --for=condition=Ready pods -n kubeflow -l app.kubernetes.io/part-of=kubeflow-dashboard --timeout=180s || (
  dump_dashboard_debug
  exit 1
)
