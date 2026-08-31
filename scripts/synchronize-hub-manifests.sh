#!/usr/bin/env bash
# This script helps to create a PR to update the Model Registry manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="hub"
REPOSITORY_NAME="kubeflow/hub"
REPOSITORY_URL="https://github.com/kubeflow/hub.git"
COMMIT="v0.3.16"
REPOSITORY_DIRECTORY="hub"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/kubeflow-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-kubeflow-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
HELM_CHART_DIRECTORY="${MANIFESTS_DIRECTORY}/experimental/helm/charts/${COMPONENT_NAME}"
HELM_CI_VALUES_FILES=(
  "${HELM_CHART_DIRECTORY}/ci/ci-values.yaml"
  "${HELM_CHART_DIRECTORY}/ci/values-db.yaml"
  "${HELM_CHART_DIRECTORY}/ci/values-postgres.yaml"
  "${HELM_CHART_DIRECTORY}/ci/values-ui.yaml"
  "${HELM_CHART_DIRECTORY}/ci/values-ui-standalone.yaml"
  "${HELM_CHART_DIRECTORY}/ci/values-ui-integrated.yaml"
  "${HELM_CHART_DIRECTORY}/ci/values-ui-istio.yaml"
)
SOURCE_MANIFESTS_PATH="manifests/kustomize"
DESTINATION_MANIFESTS_PATH="applications/${COMPONENT_NAME}/upstream"
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/tree/.*/manifests/kustomize)"
DESTINATION_TEXT="\[${COMMIT}\](https://github.com/${REPOSITORY_NAME}/tree/${COMMIT}/manifests/kustomize)"
create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"
copy_manifests "${SOURCE_DIRECTORY}/${REPOSITORY_DIRECTORY}/${SOURCE_MANIFESTS_PATH}" "${MANIFESTS_DIRECTORY}/${DESTINATION_MANIFESTS_PATH}"
sed -i "s|^  imageTag: .*|  imageTag: ${COMMIT}|" "${HELM_CHART_DIRECTORY}/values.yaml"
for helm_ci_values_file in "${HELM_CI_VALUES_FILES[@]}"; do
  sed -i "s|^    tag: \"v[^\"]*\"$|    tag: \"${COMMIT}\"|" "$helm_ci_values_file"
done
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" "$MANIFESTS_DIRECTORY"
echo "Synchronization completed successfully."
