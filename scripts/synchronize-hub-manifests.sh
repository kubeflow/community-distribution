#!/usr/bin/env bash
# This script helps to create a PR to update the Model Registry manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="hub"
REPOSITORY_NAME="kubeflow/hub"
REPOSITORY_URL="https://github.com/kubeflow/hub.git"
COMMIT="v0.3.17"
REPOSITORY_DIRECTORY="hub"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/kubeflow-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-kubeflow-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname "$SCRIPT_DIRECTORY")
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
require_helm_major_version 4
create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"
copy_manifests "${SOURCE_DIRECTORY}/${REPOSITORY_DIRECTORY}/${SOURCE_MANIFESTS_PATH}" "${MANIFESTS_DIRECTORY}/${DESTINATION_MANIFESTS_PATH}"
sed -i "s|^  imageTag: .*|  imageTag: ${COMMIT}|" "${HELM_CHART_DIRECTORY}/values.yaml"
for helm_ci_values_file in "${HELM_CI_VALUES_FILES[@]}"; do
  sed -i "s|^    tag: \"v[^\"]*\"$|    tag: \"${COMMIT}\"|" "$helm_ci_values_file"
done
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
for chart_name in helm helm-catalog; do
  update_helm_chart_application_version "${MANIFESTS_DIRECTORY}/applications/hub/${chart_name}/Chart.yaml" "$COMMIT"
done
python3 "${SCRIPT_DIRECTORY}/generate-hub-registry-helm-manifests.py" --repository-root "$MANIFESTS_DIRECTORY"
python3 "${SCRIPT_DIRECTORY}/generate-hub-catalog-helm-manifests.py" --repository-root "$MANIFESTS_DIRECTORY"
# Public baseline values are for lint/comparison only, never installation.
helm lint "${MANIFESTS_DIRECTORY}/applications/hub/helm" --namespace kubeflow-user-example-com \
  -f "${MANIFESTS_DIRECTORY}/applications/hub/helm/ci/values-platform.yaml"
helm lint "${MANIFESTS_DIRECTORY}/applications/hub/helm-catalog" --namespace kubeflow \
  -f "${MANIFESTS_DIRECTORY}/applications/hub/helm-catalog/ci/values-platform.yaml"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" \
  "$DESTINATION_MANIFESTS_PATH" \
  "applications/hub/helm/Chart.yaml" "applications/hub/helm/manifests" \
  "applications/hub/helm-catalog/Chart.yaml" "applications/hub/helm-catalog/manifests" \
  "${HELM_CHART_DIRECTORY}/values.yaml" "${HELM_CI_VALUES_FILES[@]}" \
  "README.md"
echo "Synchronization completed successfully."
