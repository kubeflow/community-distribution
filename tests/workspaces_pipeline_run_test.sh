#!/bin/bash
set -euxo pipefail

KF_PROFILE=${1:-kubeflow-user-example-com}

kubectl apply -f applications/workspaces/upstream/controller/samples/jupyterlab_v1beta1_workspacekind.yaml
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
