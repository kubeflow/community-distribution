#!/bin/bash
set -euxo pipefail

KF_PROFILE=${1:-kubeflow-user-example-com}

patch_workspacekind_for_restricted_pss() {
  kubectl patch workspacekind jupyterlab --type=json -p='[
    {
      "op": "add",
      "path": "/spec/podTemplate/securityContext/seccompProfile",
      "value": {
        "type": "RuntimeDefault"
      }
    },
    {
      "op": "add",
      "path": "/spec/podTemplate/containerSecurityContext/runAsUser",
      "value": 1000
    },
    {
      "op": "add",
      "path": "/spec/podTemplate/containerSecurityContext/seccompProfile",
      "value": {
        "type": "RuntimeDefault"
      }
    }
  ]'
  kubectl get workspacekind jupyterlab -o yaml
}

kubectl apply -f applications/workspaces/upstream/controller/samples/jupyterlab_v1beta1_workspacekind.yaml
patch_workspacekind_for_restricted_pss
kubectl apply -f tests/workspace.test.kubeflow-user-example-com.yaml
kubectl wait --for=jsonpath='{.status.state}'=Running workspace/test -n "${KF_PROFILE}" --timeout=600s

WORKSPACE_POD="$(kubectl -n "${KF_PROFILE}" get pods \
  -l notebooks.kubeflow.org/workspace-name=test \
  -o jsonpath='{.items[0].metadata.name}')"

kubectl -n "${KF_PROFILE}" cp \
  ./tests/pipeline_run_and_wait_kubeflow.py \
  "${WORKSPACE_POD}:/home/jovyan/pipeline_run_and_wait_kubeflow.py"

kubectl -n "${KF_PROFILE}" exec -ti \
  "${WORKSPACE_POD}" -- python /home/jovyan/pipeline_run_and_wait_kubeflow.py
