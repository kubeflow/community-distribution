#!/usr/bin/env bash
# This script helps to create a pull request to update the Kubeflow Pipelines manifests.
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="pipelines"
REPOSITORY_NAME="kubeflow/pipelines"
REPOSITORY_URL="https://github.com/kubeflow/pipelines.git"
COMPONENT_VERSION="2.17.1"
REPOSITORY_DIRECTORY="pipelines"
SOURCE_DIRECTORY="${SOURCE_DIRECTORY:=/tmp/kubeflow-${COMPONENT_NAME}}"
BRANCH_NAME="${BRANCH_NAME:=synchronize-kubeflow-${COMPONENT_NAME}-manifests-${COMPONENT_VERSION?}}"
MANIFESTS_DIRECTORY="$(dirname "$SCRIPT_DIRECTORY")"
SOURCE_MANIFESTS_PATH="manifests/kustomize"
DESTINATION_MANIFESTS_PATH="applications/pipeline/upstream"
HELM_CHART_PATH="applications/pipeline/helm"
HELM_CHART_DIRECTORY="${MANIFESTS_DIRECTORY}/${HELM_CHART_PATH}"
HELM_CHART_YAML="${HELM_CHART_DIRECTORY}/Chart.yaml"
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/tree/.*/manifests/kustomize)"
DESTINATION_TEXT="\[${COMPONENT_VERSION}\](https://github.com/${REPOSITORY_NAME}/tree/${COMPONENT_VERSION}/manifests/kustomize)"

update_pipelines_helm_chart() {
    "${SCRIPT_DIRECTORY}/generate-pipelines-helm-manifests.py" \
        --repository-root "$MANIFESTS_DIRECTORY"

    update_helm_chart_application_version \
        "$HELM_CHART_YAML" \
        "$COMPONENT_VERSION"
}

create_branch "$BRANCH_NAME"
clone_and_checkout \
    "$SOURCE_DIRECTORY" \
    "$REPOSITORY_URL" \
    "$REPOSITORY_DIRECTORY" \
    "$COMPONENT_VERSION"
copy_manifests "${SOURCE_DIRECTORY}/${REPOSITORY_DIRECTORY}/${SOURCE_MANIFESTS_PATH}" "${MANIFESTS_DIRECTORY}/${DESTINATION_MANIFESTS_PATH}"
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
update_pipelines_helm_chart
commit_changes \
    "$MANIFESTS_DIRECTORY" \
    "Update ${REPOSITORY_NAME} manifests from ${COMPONENT_VERSION}" \
    "${DESTINATION_MANIFESTS_PATH}" \
    "${HELM_CHART_PATH}/Chart.yaml" \
    "${HELM_CHART_PATH}/manifests" \
    "${HELM_CHART_PATH}/templates" \
    "${SCRIPT_DIRECTORY}/generate-pipelines-helm-manifests.py" \
    "${SCRIPT_DIRECTORY}/synchronize-pipelines-manifests.sh" \
    "README.md"
echo "Synchronization completed successfully."
