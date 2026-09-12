#!/usr/bin/env bash
# This script helps to create a PR to update the Spark Operator manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="spark-operator"
REPOSITORY_NAME="kubeflow/spark-operator"
REPOSITORY_URL="https://github.com/kubeflow/spark-operator.git"
COMMIT="v2.5.2"
REPOSITORY_DIRECTORY="${COMPONENT_NAME}"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/kubeflow-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
COMPONENT_PATH="applications/spark/${COMPONENT_NAME}"
DESTINATION_MANIFESTS_PATH="${COMPONENT_PATH}/base"
CHART_PATH="${COMPONENT_PATH}/helm"
CHART_DIRECTORY="${MANIFESTS_DIRECTORY}/${CHART_PATH}"
SOURCE_TEXT="\[[^]]*\](https://github.com/${REPOSITORY_NAME}/tree/[^)]*)"
DESTINATION_TEXT="\[${COMMIT#v}\](https://github.com/${REPOSITORY_NAME}/tree/${COMMIT})"

# Keep the developer's Helm home untouched when resolving the chart dependency.
HELM_HOME_DIRECTORY="$(mktemp -d)"
cleanup() {
  rm -rf "$HELM_HOME_DIRECTORY"
}
trap cleanup EXIT
export HELM_CACHE_HOME="$HELM_HOME_DIRECTORY/cache"
export HELM_CONFIG_HOME="$HELM_HOME_DIRECTORY/config"
export HELM_DATA_HOME="$HELM_HOME_DIRECTORY/data"

update_spark_operator_helm_chart() {
    update_helm_chart_application_version "$CHART_DIRECTORY/Chart.yaml" "${COMMIT#v}"

    # The wrapper depends on exactly the chart version this baseline was
    # rendered from. A range would let two installations render differently and
    # the parity comparison would stop proving anything.
    sed -i "s|  version: \"[0-9][^\"]*\"|  version: \"${COMMIT#v}\"|g" \
      "$CHART_DIRECTORY/Chart.yaml"
    sed -i "s|upstream Spark Operator \`v[^\`]*\`|upstream Spark Operator \`${COMMIT}\`|g" \
      "$CHART_DIRECTORY/README.md"
}

validate_spark_operator_helm_chart() {
    helm repo add spark-operator https://kubeflow.github.io/spark-operator >/dev/null 2>&1 \
      || helm repo update spark-operator >/dev/null
    helm dependency update "$CHART_DIRECTORY"

    # The chart refuses any namespace but kubeflow, so the linter needs it too.
    helm lint "$CHART_DIRECTORY" --namespace kubeflow
    # Parity is compared in continuous integration, by the
    # "Compare ${COMPONENT_NAME}" job, with its pinned Helm version.

    # The dependency archive is a build artifact and is never committed. Remove
    # it after the comparison, which resolves the dependency again and would
    # otherwise leave a fresh copy behind.
    rm -f "$CHART_DIRECTORY"/charts/*.tgz
    rmdir "$CHART_DIRECTORY/charts" 2>/dev/null || true
}

create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"
helm template -n kubeflow --include-crds spark-operator \
--set "spark.jobNamespaces={}" \
--set webhook.enable=true \
--set webhook.port=9443 \
"${SOURCE_DIRECTORY}/${REPOSITORY_DIRECTORY}/charts/spark-operator-chart" > "${MANIFESTS_DIRECTORY}/${DESTINATION_MANIFESTS_PATH}/resources.yaml"
update_spark_operator_helm_chart
validate_spark_operator_helm_chart
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"

# An upstream release that changes a resource the chart configures makes the
# comparison above fail until the chart follows, so the component-owned chart
# paths belong to a synchronization change and are staged with it.
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" \
  "${DESTINATION_MANIFESTS_PATH}" \
  "${CHART_PATH}/Chart.yaml" \
  "${CHART_PATH}/Chart.lock" \
  "${CHART_PATH}/values.yaml" \
  "${CHART_PATH}/templates" \
  "${CHART_PATH}/ci" \
  "${CHART_PATH}/README.md" \
  "scripts/synchronize-spark-operator-manifests.sh" \
  "README.md"
echo "Synchronization completed successfully."
