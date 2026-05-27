#!/bin/bash
set -euxo pipefail
KF_PROFILE=${1:-kubeflow-user-example-com}

dump_training_operator_debug() {
  kubectl get pytorchjob pytorch-simple -n "$KF_PROFILE" -o yaml || true
  kubectl get pods -n "$KF_PROFILE" -o wide --show-labels || true
  kubectl describe pytorchjob pytorch-simple -n "$KF_PROFILE" || true
  kubectl describe pods -n "$KF_PROFILE" || true
  kubectl get events -n "$KF_PROFILE" --sort-by=.metadata.creationTimestamp || true
  kubectl logs -n kubeflow deployment/training-operator --tail=100 || true
}

sed 's/name: pytorch-simple/name: pytorch-simple\n  namespace: '"$KF_PROFILE"'/g' \
  tests/training_operator_job.yaml > /tmp/pytorch-job.yaml
kubectl apply -f /tmp/pytorch-job.yaml

kubectl wait --for=condition=Created pytorchjob.kubeflow.org/pytorch-simple -n "$KF_PROFILE" --timeout=180s || (
  dump_training_operator_debug
  exit 1
)

kubectl get pods -n "$KF_PROFILE" --show-labels

kubectl wait --for=condition=Ready pod -l training.kubeflow.org/replica-type=master -n "$KF_PROFILE" --timeout=240s || (
  dump_training_operator_debug
  exit 1
)

kubectl wait --for=condition=Ready pod -l training.kubeflow.org/replica-type=worker -n "$KF_PROFILE" --timeout=240s || (
  dump_training_operator_debug
  exit 1
)

echo "Checking PyTorchJob status..."
kubectl get pytorchjob pytorch-simple -n "$KF_PROFILE" -o yaml

echo "Checking pod logs for debugging..."
kubectl logs -l training.kubeflow.org/replica-type=master -n "$KF_PROFILE" --tail=50 || echo "Master logs not available yet"
kubectl logs -l training.kubeflow.org/replica-type=worker -n "$KF_PROFILE" --tail=50 || echo "Worker logs not available yet"

kubectl wait --for=condition=Succeeded pytorchjob/pytorch-simple -n "$KF_PROFILE" --timeout=300s || (
  dump_training_operator_debug
  exit 1
)
