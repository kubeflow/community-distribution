#!/bin/bash
set -euxo pipefail

# The Kubeflow SDK is installed unpinned below, so this test always runs against the
# latest stable release. Spark support in the SDK is new and its API is still settling,
# so an SDK release can break this test with no change in this repository.
on_failure() {
  echo "::error::Spark Connect from Notebook test failed. If this started without a" \
    "related change here, a new Kubeflow SDK release may have changed the Spark API." \
    "Please open an issue and assign @vikas-saxena02 for triage."
}
trap on_failure ERR

KF_PROFILE="kubeflow-user-example-com"

kubectl apply -f tests/notebook.spark.test.kubeflow-user-example-com.yaml
kubectl wait --for=jsonpath='{.status.readyReplicas}'=1 \
  -f tests/notebook.spark.test.kubeflow-user-example-com.yaml \
  --timeout=600s

# The notebook-controller names the StatefulSet after the Notebook, so the pod is
# "{NOTEBOOK_NAME}-0", as tests/pipeline_run_from_notebook.yaml also relies on.
NOTEBOOK_POD="spark-test-0"

# Unlike a Workspace, a Notebook runs as "default-editor", which the Profile already
# binds to "kubeflow-edit". The aggregated "kubeflow-spark-edit" ClusterRole carries
# sparkconnects, so no extra grant is needed. Assert that here, so a regression in the
# aggregation fails with a clear message rather than inside Spark.
kubectl auth can-i create sparkconnects \
  --as="system:serviceaccount:${KF_PROFILE}:default-editor" \
  -n "${KF_PROFILE}" | grep -qx yes

# Install the Kubeflow SDK with its "spark" extra at the latest stable release, rather
# than the older copy the Notebook image ships. The resolver reports protobuf conflicts
# against the pre-installed kfp packages; they do not affect Spark.
kubectl -n "${KF_PROFILE}" exec "${NOTEBOOK_POD}" -- \
  python -m pip install --quiet --upgrade "kubeflow[spark]"

# Pin the Spark Connect client to the server version the SDK will provision. The spark
# extra and constants.DEFAULT_SPARK_VERSION can disagree -- in SDK 0.5.0 the extra pins
# pyspark-connect 4.2.0 while the constant is 4.0.4 -- so derive the client version from
# the constant rather than trusting the extra. If a future SDK changes either value, the
# test fails here, which is the right place to find out.
SPARK_VERSION="$(kubectl -n "${KF_PROFILE}" exec "${NOTEBOOK_POD}" -- python -c \
  'from kubeflow.spark.backends.kubernetes import constants; print(constants.DEFAULT_SPARK_VERSION)')"
echo "SDK default Spark version: ${SPARK_VERSION}"

kubectl -n "${KF_PROFILE}" exec "${NOTEBOOK_POD}" -- \
  python -m pip install --quiet "pyspark-connect==${SPARK_VERSION}"

# The session script is shared with the Workspaces test: creating a Spark Connect
# session is identical from either, so only the host pod differs.
kubectl -n "${KF_PROFILE}" cp \
  ./tests/spark_connect_session.py \
  "${NOTEBOOK_POD}:/home/jovyan/spark_connect_session.py"

kubectl -n "${KF_PROFILE}" exec "${NOTEBOOK_POD}" -- \
  env KF_PROFILE="${KF_PROFILE}" \
  python /home/jovyan/spark_connect_session.py
