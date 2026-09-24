#!/usr/bin/env bash
# This script helps to create a PR to update the Trainer manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="trainer"
REPOSITORY_NAME="kubeflow/trainer"
REPOSITORY_URL="https://github.com/kubeflow/trainer.git"
COMMIT="v2.3.0"
REPOSITORY_DIRECTORY="trainer"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/kubeflow-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname "$SCRIPT_DIRECTORY")
SOURCE_MANIFESTS_PATH="manifests"
DESTINATION_MANIFESTS_PATH="applications/${COMPONENT_NAME}/upstream"
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/tree/.*/manifests)"
DESTINATION_TEXT="\[${COMMIT}\](https://github.com/${REPOSITORY_NAME}/tree/${COMMIT}/manifests)"
create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"
mkdir -p "${MANIFESTS_DIRECTORY}/$(dirname "${DESTINATION_MANIFESTS_PATH}")"
copy_manifests "${SOURCE_DIRECTORY}/${REPOSITORY_DIRECTORY}/${SOURCE_MANIFESTS_PATH}" "${MANIFESTS_DIRECTORY}/${DESTINATION_MANIFESTS_PATH}"
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
require_helm_major_version 4
python3 "${SCRIPT_DIRECTORY}/generate-trainer-helm-manifests.py" \
    --repository-root "$MANIFESTS_DIRECTORY"
for chart in helm-crds helm-crds/charts/trainer-api-payload helm helm-runtimes; do
    update_helm_chart_application_version \
        "${MANIFESTS_DIRECTORY}/applications/trainer/${chart}/Chart.yaml" "$COMMIT"
    helm lint "${MANIFESTS_DIRECTORY}/applications/trainer/${chart}" \
        --namespace kubeflow-system
done
# Only the paths that this synchronization writes or owns are staged: the
# imported upstream subtree, the four Chart.yaml files whose appVersion it
# sets, the three payload directories that the generator replaces, the
# generator, this script and the README. A payload directory is staged as a
# directory so that a definition removed upstream is staged as a deletion.
# The hand-written chart files are not staged; a maintainer who has to correct
# one of them after an upstream change commits that correction deliberately.
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" \
    "$DESTINATION_MANIFESTS_PATH" \
    applications/trainer/helm-crds/Chart.yaml \
    applications/trainer/helm-crds/charts/trainer-api-payload/Chart.yaml \
    applications/trainer/helm-crds/charts/trainer-api-payload/manifests \
    applications/trainer/helm/Chart.yaml \
    applications/trainer/helm/manifests \
    applications/trainer/helm-runtimes/Chart.yaml \
    applications/trainer/helm-runtimes/manifests \
    scripts/generate-trainer-helm-manifests.py \
    scripts/synchronize-trainer-manifests.sh \
    README.md
echo "Synchronization completed successfully."
