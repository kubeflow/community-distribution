#!/bin/bash
set -euxo pipefail

KF_PROFILE=${1:-kubeflow-user-example-com}

kubectl apply -f tests/katib_test.yaml
kubectl wait --for=condition=Running experiments.kubeflow.org -n "$KF_PROFILE" --all --timeout=180s
echo "Waiting for all Trials to be Completed..."
kubectl wait --for=condition=Created trials.kubeflow.org -n "$KF_PROFILE" --all --timeout=180s
kubectl get trials.kubeflow.org -n "$KF_PROFILE"
kubectl wait --for=condition=Succeeded trials.kubeflow.org -n "$KF_PROFILE" --all --timeout 600s
kubectl get trials.kubeflow.org -n "$KF_PROFILE"
