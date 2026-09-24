#!/usr/bin/env bash
# This script helps to create a PR to update the notebooks-v2 manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="workspaces"
REPOSITORY_NAME="kubeflow/notebooks"
REPOSITORY_URL="https://github.com/kubeflow/notebooks.git"
COMMIT="v2.0.0-beta.2"
REPOSITORY_DIRECTORY="$COMPONENT_NAME"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"
copy_component_manifests() {
    local source_manifests_path=$1
    local destination_manifests_path=$2
    local readme_path_pattern_for_replacement=$3
    local destination_directory="${MANIFESTS_DIRECTORY}/${destination_manifests_path}"
    if [ -d "$destination_directory" ]; then
        rm -r "$destination_directory"
    fi
    mkdir -p "$destination_directory"
    cp "${SOURCE_DIRECTORY}/${REPOSITORY_DIRECTORY}/${source_manifests_path}/"* "$destination_directory" -r

    if [[ -n "${readme_path_pattern_for_replacement}" ]]; then
        local source_text="\[.*\](https://github.com/${REPOSITORY_NAME}/tree/.*/components/${readme_path_pattern_for_replacement})"
        local destination_text="\[${COMMIT}\](https://github.com/${REPOSITORY_NAME}/tree/${COMMIT}/components/${readme_path_pattern_for_replacement})"
        update_readme "$MANIFESTS_DIRECTORY" "$source_text" "$destination_text"
    fi
}

HELM_CHART_PATH="applications/workspaces/helm"
HELM_CHART_DIRECTORY="${MANIFESTS_DIRECTORY}/${HELM_CHART_PATH}"

update_workspaces_helm_chart() {
    local chart_yaml="${HELM_CHART_DIRECTORY}/Chart.yaml"

    update_helm_chart_application_version "$chart_yaml" "$COMMIT"
    python3 "${SCRIPT_DIRECTORY}/generate-workspaces-helm-manifests.py" \
        --repository-root "$MANIFESTS_DIRECTORY"
}

validate_workspaces_helm_chart() {
    # The chart refuses any release namespace but kubeflow, so the linter needs
    # it too.
    helm lint "$HELM_CHART_DIRECTORY" --namespace kubeflow
    # Parity is compared in continuous integration, by the
    # "Compare kubeflow-workspaces" job, with its pinned Helm version.
}

for component in {backend,frontend,controller}; do
    copy_component_manifests "workspaces/${component}/manifests/kustomize/" \
        "applications/workspaces/upstream/${component}" ""
done

update_workspaces_helm_chart
validate_workspaces_helm_chart

# An upstream change that the chart cannot absorb makes the continuous
# integration comparison fail until a maintainer edits the chart. The
# component-owned chart paths are therefore part of a synchronization change
# and are staged with it.
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests to ${COMMIT}" \
  "${SCRIPT_DIRECTORY}/synchronize-kubeflow-workspaces-manifests.sh" \
  "applications/workspaces/upstream/" \
  "${HELM_CHART_PATH}/Chart.yaml" \
  "${HELM_CHART_PATH}/kustomize/kustomization.yaml" \
  "${HELM_CHART_PATH}/manifests" \
  "${HELM_CHART_PATH}/templates" \
  "${HELM_CHART_PATH}/values.yaml" \
  "${HELM_CHART_PATH}/ci" \
  "${HELM_CHART_PATH}/README.md" \
  "${SCRIPT_DIRECTORY}/helm_manifest_generator.py" \
  "${SCRIPT_DIRECTORY}/generate-workspaces-helm-manifests.py"
echo "Synchronization completed successfully."
