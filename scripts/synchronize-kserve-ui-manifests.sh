#!/usr/bin/env bash
# This script helps to create a PR to update the KServe UI manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="kserve-ui"
REPOSITORY_NAME="kserve/models-web-app"
REPOSITORY_URL="https://github.com/kserve/models-web-app.git"
COMMIT="v1.0.0"
REPOSITORY_DIRECTORY="models-web-app"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/kserve-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-kserve-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
SOURCE_MANIFESTS_PATH="manifests/kustomize"
DESTINATION_MANIFESTS_PATH="applications/kserve/${COMPONENT_NAME}/upstream"
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/tree/.*)"
DESTINATION_TEXT="\[${COMMIT}\](https://github.com/${REPOSITORY_NAME}/tree/${COMMIT}/${SOURCE_MANIFESTS_PATH})"
create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"
copy_manifests "${SOURCE_DIRECTORY}/${REPOSITORY_DIRECTORY}/${SOURCE_MANIFESTS_PATH}" "${MANIFESTS_DIRECTORY}/${DESTINATION_MANIFESTS_PATH}"
# Upstream pins the container image tag independently of the Git tag, so align both the Kustomize overlay in the applications directory and the Helm values with the targeted COMMIT.
IMAGE_TAG="${COMMIT#v}"
sed -i "s|newTag: .*|newTag: ${IMAGE_TAG}|" "${MANIFESTS_DIRECTORY}/applications/kserve/${COMPONENT_NAME}/kustomization.yaml"
sed -i "s|imageTag: .*|imageTag: ${IMAGE_TAG}|" "${MANIFESTS_DIRECTORY}/experimental/helm/charts/${COMPONENT_NAME}/values.yaml"
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" "$MANIFESTS_DIRECTORY"
echo "Synchronization completed successfully."
