#!/usr/bin/env bash
# This script helps to create a PR to update the Kubeflow manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="kubeflow-dashboard"
REPOSITORY_NAME="kubeflow/dashboard"
REPOSITORY_URL="https://github.com/kubeflow/dashboard.git"
COMMIT="v2.0.0"
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
TARGET_DIRECTORY="applications/dashboard/upstream"
HELM_CHART_PATH="applications/dashboard/helm"
HELM_CHART_DIRECTORY="${MANIFESTS_DIRECTORY}/${HELM_CHART_PATH}"

update_dashboard_helm_chart() {
    local chart_yaml="${HELM_CHART_DIRECTORY}/Chart.yaml"

    update_helm_chart_application_version "$chart_yaml" "$COMMIT"
    python3 "${SCRIPT_DIRECTORY}/generate-dashboard-helm-manifests.py" \
        --repository-root "$MANIFESTS_DIRECTORY"
}

validate_dashboard_helm_chart() {
    # The chart refuses any namespace but kubeflow, so the linter needs it too.
    helm lint "$HELM_CHART_DIRECTORY" --namespace kubeflow
    # Parity is compared in continuous integration, by the
    # "Compare ${COMPONENT_NAME}" job, with its pinned Helm version.
}

copy_component_manifests "components/poddefaults-webhooks/manifests/kustomize" \
    "${TARGET_DIRECTORY}/poddefaults-webhooks"
copy_component_manifests "components/centraldashboard/manifests/kustomize" \
    "${TARGET_DIRECTORY}/centraldashboard"
copy_component_manifests "components/profile-controller/manifests/kustomize" \
    "${TARGET_DIRECTORY}/profile-controller"
update_dashboard_helm_chart
validate_dashboard_helm_chart
# The script regenerates the payloads and Chart.yaml; the hand-written chart
# files are staged with them so that re-running the script reproduces the
# commit exactly. An upstream change to a hand-written resource additionally
# needs a template correction, which the comparison job reports on the pull
# request.
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" \
  "${TARGET_DIRECTORY}" \
  "${HELM_CHART_PATH}/Chart.yaml" \
  "${HELM_CHART_PATH}/kustomize/kustomization.yaml" \
  "${HELM_CHART_PATH}/manifests" \
  "${HELM_CHART_PATH}/templates" \
  "${HELM_CHART_PATH}/values.yaml" \
  "${HELM_CHART_PATH}/ci" \
  "${HELM_CHART_PATH}/README.md" \
  "${SCRIPT_DIRECTORY}/helm_manifest_generator.py" \
  "${SCRIPT_DIRECTORY}/generate-dashboard-helm-manifests.py" \
  "${SCRIPT_DIRECTORY}/synchronize-dashboard-manifests.sh" \
  "README.md"
echo "Synchronization completed successfully."
