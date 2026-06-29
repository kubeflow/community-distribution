#!/usr/bin/env bash
# This script helps to create a PR to update the KServe manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="kserve"
REPOSITORY_NAME="kserve/kserve"
REPOSITORY_URL="https://github.com/kserve/kserve.git"
COMMIT="v0.19.0"
REPOSITORY_DIRECTORY="kserve"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
SOURCE_MANIFESTS_PATH="install/${COMMIT}"
DESTINATION_MANIFESTS_PATH="applications/${COMPONENT_NAME}/${COMPONENT_NAME}/upstream"
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/tree/.*)"
DESTINATION_TEXT="\[${COMMIT}\](https://github.com/${REPOSITORY_NAME}/tree/${COMMIT})"
create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"
DESTINATION_DIRECTORY=$MANIFESTS_DIRECTORY/$DESTINATION_MANIFESTS_PATH

copy_manifests "$SOURCE_DIRECTORY/$REPOSITORY_DIRECTORY/$SOURCE_MANIFESTS_PATH/" "$DESTINATION_DIRECTORY"

# Delete upstream kserve scripts shipped in the manifests directories
find "$DESTINATION_DIRECTORY" -maxdepth 1 -name '*.sh' -delete

update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests to version ${COMMIT}" \
    "${MANIFESTS_DIRECTORY}/applications/kserve/kserve/upstream" \
    "${SCRIPT_DIRECTORY}/synchronize-kserve-kserve-manifests.sh" \
    "${MANIFESTS_DIRECTORY}/README.md"
echo "Synchronization completed successfully."
