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

kubectl patch clustertrainingruntime torch-distributed --type=json -p='[
  {
    "op": "add",
    "path": "/spec/template/spec/replicatedJobs/0/template/spec/template/spec/securityContext",
    "value": {
      "runAsNonRoot": true,
      "runAsUser": 1000,
      "seccompProfile": {"type": "RuntimeDefault"}
    }
  },
  {
    "op": "add",
    "path": "/spec/template/spec/replicatedJobs/0/template/spec/template/spec/containers/0/workingDir",
    "value": "/tmp"
  },
  {
    "op": "add",
    "path": "/spec/template/spec/replicatedJobs/0/template/spec/template/spec/containers/0/securityContext",
    "value": {
      "allowPrivilegeEscalation": false,
      "capabilities": {"drop": ["ALL"]},
      "runAsNonRoot": true,
      "runAsUser": 1000,
      "seccompProfile": {"type": "RuntimeDefault"}
    }
  }
]'
kubectl get clustertrainingruntime torch-distributed -o yaml

pip install kubeflow
python3 tests/trainer_test.py "$KF_PROFILE"
