#!/usr/bin/env bash
# This script helps to create a PR to update the Notebooks v1 manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="notebooks-v1"
REPOSITORY_NAME="kubeflow/notebooks"
REPOSITORY_URL="https://github.com/kubeflow/notebooks.git"
COMMIT="v1.11.0"
REPOSITORY_DIRECTORY="$COMPONENT_NAME"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/${COMPONENT_NAME}-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"
copy_component_manifests() {
    local source_manifests_path=$1
    local destination_manifests_path=$2
    local destination_directory="${MANIFESTS_DIRECTORY}/${destination_manifests_path}"
    if [ -d "$destination_directory" ]; then
        rm -r "$destination_directory"
    fi
    mkdir -p "$destination_directory"
    cp "${SOURCE_DIRECTORY}/${REPOSITORY_DIRECTORY}/${source_manifests_path}/"* "$destination_directory" -r
    local source_text="\[.*\](https://github.com/${REPOSITORY_NAME}/tree/.*/)"
    local destination_text="\[${COMMIT}\](https://github.com/${REPOSITORY_NAME}/tree/${COMMIT}/)"
    update_readme "$MANIFESTS_DIRECTORY" "$source_text" "$destination_text"
}
TARGET_DIRECTORY="applications/notebooks-v1/upstream"
HELM_CHART_PATH="applications/notebooks-v1/helm"
HELM_CHART_DIRECTORY="${MANIFESTS_DIRECTORY}/${HELM_CHART_PATH}"
COMPONENT_NAME="kubeflow-notebooks"

update_notebooks_helm_chart() {
    local chart_yaml="${HELM_CHART_DIRECTORY}/Chart.yaml"

    update_helm_chart_application_version "$chart_yaml" "$COMMIT"
    python3 "${SCRIPT_DIRECTORY}/generate-notebooks-v1-helm-manifests.py" \
        --repository-root "$MANIFESTS_DIRECTORY"
}

validate_notebooks_helm_chart() {
    # The chart refuses any namespace but kubeflow, so the linter needs it too.
    helm lint "$HELM_CHART_DIRECTORY" --namespace kubeflow
    # Parity is compared in continuous integration, by the
    # "Compare ${COMPONENT_NAME}" job, with its pinned Helm version.
}

copy_component_manifests "components/crud-web-apps/jupyter/manifests" \
    "${TARGET_DIRECTORY}/jupyter-web-app"
copy_component_manifests "components/crud-web-apps/volumes/manifests" \
    "${TARGET_DIRECTORY}/volumes-web-app"
copy_component_manifests "components/crud-web-apps/tensorboards/manifests" \
    "${TARGET_DIRECTORY}/tensorboards-web-app"
copy_component_manifests "components/notebook-controller/config" \
    "${TARGET_DIRECTORY}/notebook-controller"
copy_component_manifests "components/tensorboard-controller/config" \
    "${TARGET_DIRECTORY}/tensorboard-controller"
copy_component_manifests "components/pvcviewer-controller/config" \
    "${TARGET_DIRECTORY}/pvcviewer-controller"

update_notebooks_helm_chart
validate_notebooks_helm_chart

# An upstream change that the chart cannot absorb makes the continuous
# integration comparison fail until a maintainer edits the chart. The
# component-owned chart paths are therefore part of a synchronization change
# and are staged with it.
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests to ${COMMIT}" \
  "${TARGET_DIRECTORY}" \
  "${HELM_CHART_PATH}/Chart.yaml" \
  "${HELM_CHART_PATH}/kustomize/kustomization.yaml" \
  "${HELM_CHART_PATH}/manifests" \
  "${HELM_CHART_PATH}/templates" \
  "${HELM_CHART_PATH}/values.yaml" \
  "${HELM_CHART_PATH}/ci" \
  "${HELM_CHART_PATH}/README.md" \
  "${SCRIPT_DIRECTORY}/helm_manifest_generator.py" \
  "${SCRIPT_DIRECTORY}/generate-notebooks-v1-helm-manifests.py" \
  "${SCRIPT_DIRECTORY}/synchronize-notebooks-v1-manifests.sh" \
  "README.md"
echo "Synchronization completed successfully."
