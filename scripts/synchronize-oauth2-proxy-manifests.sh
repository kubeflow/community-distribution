#!/usr/bin/env bash
# This script helps to create a PR to update the OAuth2-Proxy manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="oauth2-proxy"
REPOSITORY_NAME="oauth2-proxy/oauth2-proxy"
COMMIT="v7.15.2"
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
DESTINATION_DIRECTORY=$MANIFESTS_DIRECTORY/common/${COMPONENT_NAME}
create_branch "$BRANCH_NAME"
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i "" "s|quay.io/oauth2-proxy/oauth2-proxy:.*|quay.io/oauth2-proxy/oauth2-proxy:${COMMIT}|g" \
        $DESTINATION_DIRECTORY/base/deployment.yaml
else
    sed -i "s|quay.io/oauth2-proxy/oauth2-proxy:.*|quay.io/oauth2-proxy/oauth2-proxy:${COMMIT}|g" \
        $DESTINATION_DIRECTORY/base/deployment.yaml
fi
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/releases/tag/v.*)"
DESTINATION_TEXT="\[${COMMIT#v}\](https://github.com/${REPOSITORY_NAME}/releases/tag/${COMMIT})"
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" "$MANIFESTS_DIRECTORY"
echo "Synchronization completed successfully."
