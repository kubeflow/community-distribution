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
TARGET_DIR="applications/notebooks-v1/upstream/"

copy_component_manifests "components/crud-web-apps/jupyter/manifests" \
    "${TARGET_DIR}/jupyter-web-app/"
copy_component_manifests "components/crud-web-apps/volumes/manifests" \
    "${TARGET_DIR}/volumes-web-app/"
copy_component_manifests "components/crud-web-apps/tensorboards/manifests" \
    "${TARGET_DIR}/tensorboards-web-app/"
copy_component_manifests "components/notebook-controller/config" \
    "${TARGET_DIR}/notebook-controller/"
copy_component_manifests "components/tensorboard-controller/config" \
    "${TARGET_DIR}/tensorboard-controller"
copy_component_manifests "components/pvcviewer-controller/config" \
    "${TARGET_DIR}/pvcviewer-controller/"

commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests to ${COMMIT}" \
  "${TARGET_DIR}" \
  "${SCRIPT_DIRECTORY}/synchronize-notebooks-v1-manifests.sh" \
  "README.md"
echo "Synchronization completed successfully."
