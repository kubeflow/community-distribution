#!/bin/bash
set -euxo pipefail
KF_PROFILE=${1:-kubeflow-user-example-com}

kubectl get crd jobsets.jobset.x-k8s.io
kubectl get service jobset-webhook-service -n kubeflow-system
kubectl get mutatingwebhookconfiguration jobset-mutating-webhook-configuration
kubectl get validatingwebhookconfiguration jobset-validating-webhook-configuration

kubectl wait --for=condition=Available deployment/jobset-controller-manager -n kubeflow-system --timeout=120s
kubectl wait --for=condition=Ready pod -l control-plane=controller-manager -n kubeflow-system --timeout=60s

sleep 10
kubectl get endpoints jobset-webhook-service -n kubeflow-system

kubectl get deployment kubeflow-trainer-controller-manager -n kubeflow-system
kubectl get pods -n kubeflow-system -l app.kubernetes.io/name=trainer
kubectl get clustertrainingruntimes torch-distributed

# The Kubeflow SDK depends on kubeflow-trainer-api with a lower bound only, so the
# generated API package must be pinned to the Trainer version installed above.
pip install kubeflow kubeflow-trainer-api==2.3.0rc3
python3 tests/trainer_test.py "$KF_PROFILE"
