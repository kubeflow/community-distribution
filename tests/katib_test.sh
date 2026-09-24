#!/bin/bash
set -euxo pipefail

KF_PROFILE=${1:-kubeflow-user-example-com}

# The fixture names the default profile; apply it to the namespace under test.
sed "s/^  namespace: kubeflow-user-example-com$/  namespace: ${KF_PROFILE}/" tests/katib_test.yaml | kubectl apply -f -
kubectl wait --for=condition=Running experiments.kubeflow.org -n $KF_PROFILE --all --timeout=60s
echo "Waiting for all Trials to be Completed..."
kubectl wait --for=condition=Created trials.kubeflow.org -n $KF_PROFILE --all --timeout=60s
kubectl get trials.kubeflow.org -n $KF_PROFILE
kubectl wait --for=condition=Succeeded trials.kubeflow.org -n $KF_PROFILE --all --timeout 600s
kubectl get trials.kubeflow.org -n $KF_PROFILE
