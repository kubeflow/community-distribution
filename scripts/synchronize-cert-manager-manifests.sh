#!/usr/bin/env bash
# This script helps to create a PR to update cert-manager manifests.
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="cert-manager"
REPOSITORY_NAME="cert-manager/cert-manager"
COMMIT="v1.21.1"
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY="$(dirname "$SCRIPT_DIRECTORY")"
DESTINATION_DIRECTORY="$MANIFESTS_DIRECTORY/common/${COMPONENT_NAME}"
DESTINATION_FILE="$DESTINATION_DIRECTORY/base/upstream/cert-manager.yaml"
CHART_DIRECTORY="$DESTINATION_DIRECTORY/helm"
HELM_HOME_DIRECTORY="$(mktemp -d)"
cleanup() {
  rm -rf "$HELM_HOME_DIRECTORY"
}
trap cleanup EXIT
export HELM_CACHE_HOME="$HELM_HOME_DIRECTORY/cache"
export HELM_CONFIG_HOME="$HELM_HOME_DIRECTORY/config"
export HELM_DATA_HOME="$HELM_HOME_DIRECTORY/data"
create_branch "$BRANCH_NAME"
wget -O "$DESTINATION_FILE" \
  "https://github.com/${REPOSITORY_NAME}/releases/download/${COMMIT}/cert-manager.yaml"
sed -i "s|^appVersion: .*|appVersion: ${COMMIT}|g" \
  "$CHART_DIRECTORY/Chart.yaml"
sed -i "s|  version: \"[0-9][0-9.]*\"|  version: \"${COMMIT#v}\"|g" \
  "$CHART_DIRECTORY/Chart.yaml"
sed -i "s|upstream cert-manager \`v[0-9.]*\`|upstream cert-manager \`${COMMIT}\`|g" \
  "$CHART_DIRECTORY/README.md"
helm repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || helm repo update jetstack >/dev/null
helm dependency update "$CHART_DIRECTORY"
rm -f "$CHART_DIRECTORY"/charts/*.tgz
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/releases/tag/v.*)"
DESTINATION_TEXT="\[${COMMIT#v}\](https://github.com/${REPOSITORY_NAME}/releases/tag/${COMMIT})"
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" \
  "README.md" \
  "scripts/synchronize-cert-manager-manifests.sh" \
  "common/${COMPONENT_NAME}"
echo "Synchronization completed successfully."
