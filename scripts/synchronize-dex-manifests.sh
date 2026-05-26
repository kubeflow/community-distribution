#!/usr/bin/env bash
# This script helps to create a PR to update the Dex manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="dex"
REPOSITORY_NAME="dexidp/dex"
REPOSITORY_URL="https://github.com/dexidp/dex.git"
COMMIT="v2.45.1"
REPOSITORY_DIRECTORY="dex"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/kubeflow-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
DESTINATION_MANIFESTS_PATH="common/${COMPONENT_NAME}"
DESTINATION_DIRECTORY=$MANIFESTS_DIRECTORY/${DESTINATION_MANIFESTS_PATH}
UPSTREAM_DIRECTORY=$DESTINATION_DIRECTORY/base/upstream
create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"

sed -i "s|ghcr.io/dexidp/dex:v[0-9.]*|ghcr.io/dexidp/dex:${COMMIT}|g" \
  "$DESTINATION_DIRECTORY/base/deployment.yaml"

mkdir -p "$UPSTREAM_DIRECTORY"
cp \
  "$SOURCE_DIRECTORY/$REPOSITORY_DIRECTORY/scripts/manifests/crds/authcodes.yaml" \
  "$UPSTREAM_DIRECTORY/crds.yaml"
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/releases/tag/v.*)"
DESTINATION_TEXT="\[${COMMIT#v}\](https://github.com/${REPOSITORY_NAME}/releases/tag/${COMMIT})"
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" "$DESTINATION_MANIFESTS_PATH"
echo "Synchronization completed successfully."
