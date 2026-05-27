#!/bin/bash
set -euxo pipefail

KF_PROFILE=${1:-kubeflow-user-example-com}

dump_katib_debug() {
  kubectl get experiments.kubeflow.org -n "$KF_PROFILE" -o yaml || true
  kubectl get trials.kubeflow.org -n "$KF_PROFILE" -o yaml || true
  kubectl get jobs,pods -n "$KF_PROFILE" -o wide --show-labels || true
  kubectl describe experiments.kubeflow.org -n "$KF_PROFILE" || true
  kubectl describe trials.kubeflow.org -n "$KF_PROFILE" || true
  kubectl describe jobs,pods -n "$KF_PROFILE" || true
  kubectl get events -n "$KF_PROFILE" --sort-by=.metadata.creationTimestamp || true
  kubectl logs -n kubeflow deployment/katib-controller --tail=100 || true
}

kubectl apply -f tests/katib_test.yaml
kubectl wait --for=condition=Running experiments.kubeflow.org -n "$KF_PROFILE" --all --timeout=180s || (
  dump_katib_debug
  exit 1
)
echo "Waiting for all Trials to be Completed..."
kubectl wait --for=condition=Created trials.kubeflow.org -n "$KF_PROFILE" --all --timeout=180s || (
  dump_katib_debug
  exit 1
)
kubectl get trials.kubeflow.org -n "$KF_PROFILE"
kubectl wait --for=condition=Succeeded trials.kubeflow.org -n "$KF_PROFILE" --all --timeout 600s || (
  dump_katib_debug
  exit 1
)
kubectl get trials.kubeflow.org -n "$KF_PROFILE"
