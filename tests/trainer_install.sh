#!/bin/bash
set -euxo pipefail

cd applications/trainer

kustomize build upstream/base/crds | kubectl apply --server-side --force-conflicts -f -
sleep 5
kubectl wait --for condition=established crd/trainjobs.trainer.kubeflow.org --timeout=60s

kustomize build overlays | kubectl apply --server-side --force-conflicts -f -
kubectl wait --for=condition=Available deployment/kubeflow-trainer-controller-manager -n kubeflow-system --timeout=240s
kubectl get crd jobsets.jobset.x-k8s.io
kubectl wait --for=condition=Available deployment/jobset-controller-manager -n kubeflow-system --timeout=120s

kustomize build overlays/runtimes | kubectl apply --server-side --force-conflicts -f -
kubectl patch clustertrainingruntime torch-distributed --type='json' -p='[{"op": "add", "path": "/spec/template/spec/replicatedJobs/0/template/metadata", "value": {"labels": {"trainer.kubeflow.org/trainjob-ancestor-step": "trainer"}}}, {"op": "add", "path": "/spec/template/spec/replicatedJobs/0/template/spec/template/spec/containers/0/image", "value": "pytorch/pytorch:2.10.0-cuda12.8-cudnn9-runtime"}]'

kubectl apply -f upstream/overlays/kubeflow-platform/kubeflow-trainer-roles.yaml

cd -


kubectl get deployment -n kubeflow-system kubeflow-trainer-controller-manager
kubectl get pods -n kubeflow-system -l app.kubernetes.io/name=trainer
kubectl get crd | grep -E 'trainer.kubeflow.org'
kubectl get clustertrainingruntimes

kubectl rollout restart deployment/jobset-controller-manager -n kubeflow-system
kubectl rollout status deployment/jobset-controller-manager -n kubeflow-system --timeout=120s
kubectl wait --for=condition=Available deployment/jobset-controller-manager -n kubeflow-system --timeout=120s

# Wait for webhook certificates to be provisioned
kubectl wait --timeout=120s --for='jsonpath={.webhooks[0].clientConfig.caBundle}' validatingwebhookconfiguration/validator.trainer.kubeflow.org
kubectl wait --timeout=120s --for='jsonpath={.webhooks[0].clientConfig.caBundle}' mutatingwebhookconfiguration/jobset-mutating-webhook-configuration

# Allow kube-proxy endpoint propagation after rollout restart
sleep 30
