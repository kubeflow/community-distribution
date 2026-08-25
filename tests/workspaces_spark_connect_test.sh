#!/bin/bash
set -euxo pipefail

KF_PROFILE=${1:-kubeflow-user-example-com}

kubectl apply -f tests/workspacekind.spark.test.yaml
kubectl apply -f tests/workspace.spark.test.kubeflow-user-example-com.yaml
kubectl wait --for=jsonpath='{.status.state}'=Running \
  workspace/spark-test -n "${KF_PROFILE}" \
  --timeout=600s

WORKSPACE_POD="$(kubectl -n "${KF_PROFILE}" get pods \
  -l notebooks.kubeflow.org/workspace-name=spark-test \
  -o jsonpath='{.items[0].metadata.name}')"

# The Workspace ServiceAccount is granted kubeflow-spark-edit by the WorkspaceKind,
# so it can create SparkConnect resources. Assert that before running the session,
# so an RBAC regression fails here with a clear message rather than inside Spark.
kubectl auth can-i create sparkconnects \
  --as="system:serviceaccount:${KF_PROFILE}:ws-spark-test" \
  -n "${KF_PROFILE}" | grep -qx yes

# The jupyter-scipy image does not ship the Kubeflow SDK. Installing it here rather
# than baking a dedicated image keeps this test self-contained. The resolver reports
# protobuf conflicts against the pre-installed kfp packages; they do not affect Spark.
kubectl -n "${KF_PROFILE}" exec "${WORKSPACE_POD}" -- \
  python -m pip install --quiet "kubeflow[spark]"

kubectl -n "${KF_PROFILE}" cp \
  ./tests/spark_connect_from_workspace.py \
  "${WORKSPACE_POD}:/home/jovyan/spark_connect_from_workspace.py"

kubectl -n "${KF_PROFILE}" exec "${WORKSPACE_POD}" -- \
  env KF_PROFILE="${KF_PROFILE}" \
  python /home/jovyan/spark_connect_from_workspace.py
