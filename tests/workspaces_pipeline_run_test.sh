#!/bin/bash
set -euxo pipefail

KF_PROFILE=${1:-kubeflow-user-example-com}

kustomize build --load-restrictor LoadRestrictionsNone tests/workspaces-kustomization | kubectl apply -f -
sleep 15 # Wait for Notebook Controller to sync the new WorkspaceKind definition
kubectl apply -f tests/workspace.test.kubeflow-user-example-com.yaml
kubectl wait --for=jsonpath='{.status.state}'=Running \
  workspace/test -n "${KF_PROFILE}" \
  --timeout=600s

WORKSPACE_POD="$(kubectl -n "${KF_PROFILE}" get pods \
  -l notebooks.kubeflow.org/workspace-name=test \
  -o jsonpath='{.items[0].metadata.name}')"

kubectl -n "${KF_PROFILE}" cp \
  ./tests/pipeline_run_and_wait_kubeflow.py \
  "${WORKSPACE_POD}:/home/jovyan/pipeline_run_and_wait_kubeflow.py"

kubectl -n "${KF_PROFILE}" exec -ti \
  "${WORKSPACE_POD}" -- python /home/jovyan/pipeline_run_and_wait_kubeflow.py
