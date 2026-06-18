#!/usr/bin/env bash
# This script helps to create a PR to update the Trainer manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="trainer"
REPOSITORY_NAME="kubeflow/trainer"
REPOSITORY_URL="https://github.com/kubeflow/trainer.git"
COMMIT="v2.2.1"
REPOSITORY_DIRECTORY="trainer"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/kubeflow-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
SOURCE_MANIFESTS_PATH="manifests"
DESTINATION_MANIFESTS_PATH="applications/${COMPONENT_NAME}/upstream"
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/tree/.*/manifests)"
DESTINATION_TEXT="\[${COMMIT}\](https://github.com/${REPOSITORY_NAME}/tree/${COMMIT}/manifests)"
create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"
mkdir -p "${MANIFESTS_DIRECTORY}/$(dirname "${DESTINATION_MANIFESTS_PATH}")"
copy_manifests "${SOURCE_DIRECTORY}/${REPOSITORY_DIRECTORY}/${SOURCE_MANIFESTS_PATH}" "${MANIFESTS_DIRECTORY}/${DESTINATION_MANIFESTS_PATH}"
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" "$MANIFESTS_DIRECTORY"
echo "Synchronization completed successfully."
