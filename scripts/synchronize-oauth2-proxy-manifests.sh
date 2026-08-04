#!/usr/bin/env bash
# This script helps to create a PR to update the OAuth2-Proxy manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="oauth2-proxy"
REPOSITORY_NAME="oauth2-proxy/oauth2-proxy"
COMMIT="v7.15.3"
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY="$(dirname "$SCRIPT_DIRECTORY")"
DESTINATION_DIRECTORY="$MANIFESTS_DIRECTORY/common/${COMPONENT_NAME}"
CHART_DIRECTORY="$DESTINATION_DIRECTORY/helm"
create_branch "$BRANCH_NAME"
sed -i "s|quay.io/oauth2-proxy/oauth2-proxy:.*|quay.io/oauth2-proxy/oauth2-proxy:${COMMIT}|g" \
    "$DESTINATION_DIRECTORY/base/deployment.yaml"
update_helm_chart_application_version \
    "$CHART_DIRECTORY/Chart.yaml" "${COMMIT#v}"
sed -i "s|quay.io/oauth2-proxy/oauth2-proxy:.*|quay.io/oauth2-proxy/oauth2-proxy:${COMMIT}|g" \
    "$CHART_DIRECTORY/templates/oauth2-proxy.yaml"
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/releases/tag/v.*)"
DESTINATION_TEXT="\[${COMMIT#v}\](https://github.com/${REPOSITORY_NAME}/releases/tag/${COMMIT})"
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" \
    "README.md" \
    "scripts/synchronize-oauth2-proxy-manifests.sh" \
    "common/${COMPONENT_NAME}"
echo "Synchronization completed successfully."
