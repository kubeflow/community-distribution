#!/usr/bin/env bash
# This script helps to create a PR to update the KServe manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="kserve"
REPOSITORY_NAME="kserve/kserve"
REPOSITORY_URL="https://github.com/kserve/kserve.git"
COMMIT="ece1a7e645eaf22e15c9ae6324c0341cf0e331a4" # v0.17.0 post
MANIFESTS_VERSION="v0.17.0"
REPOSITORY_DIRECTORY="kserve"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
SOURCE_MANIFESTS_PATH="install/${COMMIT}"
DESTINATION_MANIFESTS_PATH="applications/${COMPONENT_NAME}/${COMPONENT_NAME}"
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/releases/tag/.*)"
DESTINATION_TEXT="\[${COMMIT}\](https://github.com/${REPOSITORY_NAME}/releases/tag/${COMMIT}/install/${COMMIT})"
create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"
DESTINATION_DIRECTORY=$MANIFESTS_DIRECTORY/$DESTINATION_MANIFESTS_PATH
if [ -d "$DESTINATION_DIRECTORY" ]; then
    rm -rf "$DESTINATION_DIRECTORY"/kserve*
fi
cp $SOURCE_DIRECTORY/$REPOSITORY_DIRECTORY/$SOURCE_MANIFESTS_PATH/* $DESTINATION_DIRECTORY -r
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" "$MANIFESTS_DIRECTORY"
echo "Synchronization completed successfully."
