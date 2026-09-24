#!/usr/bin/env bash
# This script helps to create a PR to update the Katib manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="katib"
REPOSITORY_NAME="kubeflow/katib"
REPOSITORY_URL="https://github.com/kubeflow/katib.git"
COMMIT="v0.19.0"
REPOSITORY_DIRECTORY="katib"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/kubeflow-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
SOURCE_MANIFESTS_PATH="manifests/v1beta1"
DESTINATION_MANIFESTS_PATH="applications/${COMPONENT_NAME}/upstream"
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/tree/.*/manifests/v1beta1)"
DESTINATION_TEXT="\[${COMMIT}\](https://github.com/${REPOSITORY_NAME}/tree/${COMMIT}/manifests/v1beta1)"
HELM_CHART_PATH="applications/${COMPONENT_NAME}/helm"
HELM_CHART_DIRECTORY="${MANIFESTS_DIRECTORY}/${HELM_CHART_PATH}"
# The distribution deviates from upstream in one imported file. The patch
# records the deviation; the two SHA-256 digests pin the file as imported from
# COMMIT and the file after the patch. An intentional change updates the patch
# and the digests in one reviewed commit.
MYSQL_MANIFEST_PATH="${DESTINATION_MANIFESTS_PATH}/components/mysql/mysql.yaml"
MYSQL_PATCH_PATH="applications/${COMPONENT_NAME}/patches/mysql-image-and-probes.patch"
MYSQL_MANIFEST_UPSTREAM_SHA256="e2ea06681f26e296df485dcf4833dbf623e4a7d02d5398bb0f31c1828ebfa8af"
MYSQL_MANIFEST_PATCHED_SHA256="4321726ab8e32187e31c3af683e1b8b0aff5eacecf41aca617b26d36cc40536a"

# commit_changes commits the whole index, so content that is staged before the
# run would become part of the synchronization commit.
require_empty_index() {
    local manifests_directory="$1"
    local status=0

    if [[ "${KUBEFLOW_SYNCHRONIZE_NO_COMMIT:-}" == "true" ]]; then
        return
    fi
    git -C "$manifests_directory" diff --cached --quiet || status=$?
    if [[ "$status" -eq 1 ]]; then
        echo "ERROR: the index of ${manifests_directory} is not empty; unstage or commit those changes first." >&2
        return 1
    elif [[ "$status" -ne 0 ]]; then
        echo "ERROR: could not read the index of ${manifests_directory}." >&2
        return 1
    fi
}

# Reapply the distribution deviation to the freshly imported MySQL manifest.
# The patch is applied to a copy outside the repository; the imported file is
# replaced only when the result has the expected digest, so every failure leaves
# the imported bytes in place. No fuzz, no fallback and no second attempt.
apply_katib_mysql_patch() {
    local manifests_directory="$1"
    local target="${manifests_directory}/${MYSQL_MANIFEST_PATH}"
    local patch="${manifests_directory}/${MYSQL_PATCH_PATH}"
    local patched_paths actual_sha256 candidate_directory candidate published

    candidate_directory="$(mktemp -d)"
    patched_paths="$(cd "$candidate_directory" && GIT_CEILING_DIRECTORIES="$(dirname "$candidate_directory")" \
        git apply --numstat "$patch" | cut -f3)"
    if [[ "$patched_paths" != "$MYSQL_MANIFEST_PATH" ]]; then
        rm -rf "$candidate_directory"
        echo "ERROR: ${MYSQL_PATCH_PATH} must change exactly ${MYSQL_MANIFEST_PATH}, found: ${patched_paths}" >&2
        return 1
    fi

    actual_sha256="$(sha256sum "$target" | cut -d' ' -f1)"
    if [[ "$actual_sha256" != "$MYSQL_MANIFEST_UPSTREAM_SHA256" ]]; then
        rm -rf "$candidate_directory"
        echo "ERROR: ${MYSQL_MANIFEST_PATH} at ${COMMIT} is not the input that ${MYSQL_PATCH_PATH} was written for (SHA-256 ${actual_sha256}). Review the patch, then update it together with both digests." >&2
        return 1
    fi

    candidate="${candidate_directory}/${MYSQL_MANIFEST_PATH}"
    mkdir -p "$(dirname "$candidate")"
    cp "$target" "$candidate"
    if ! (cd "$candidate_directory" && GIT_CEILING_DIRECTORIES="$(dirname "$candidate_directory")" \
        git -c apply.ignoreWhitespace=no -c apply.whitespace=nowarn apply "$patch"); then
        rm -rf "$candidate_directory"
        echo "ERROR: ${MYSQL_PATCH_PATH} did not apply; no fuzz or fallback is attempted." >&2
        return 1
    fi

    actual_sha256="$(sha256sum "$candidate" | cut -d' ' -f1)"
    if [[ "$actual_sha256" != "$MYSQL_MANIFEST_PATCHED_SHA256" ]]; then
        rm -rf "$candidate_directory"
        echo "ERROR: ${MYSQL_PATCH_PATH} applied, but the result differs from the reviewed result (SHA-256 ${actual_sha256})." >&2
        return 1
    fi

    published="$(mktemp "${target}.temporary.XXXXXX")"
    cp "$candidate" "$published"
    chmod --reference="$target" "$published"
    mv -f "$published" "$target"
    rm -rf "$candidate_directory"
}

update_katib_helm_chart() {
    update_helm_chart_application_version "${HELM_CHART_DIRECTORY}/Chart.yaml" "$COMMIT"
    python3 "${SCRIPT_DIRECTORY}/generate-katib-helm-manifests.py" \
        --repository-root "$MANIFESTS_DIRECTORY"
}

validate_katib_helm_chart() {
    # The chart refuses any namespace but kubeflow, so the linter needs it too.
    helm lint "$HELM_CHART_DIRECTORY" --namespace kubeflow
    # Parity is compared in continuous integration, by the "Compare katib"
    # job, with its pinned Helm version.
}

# A test sources this file for its functions and stops here.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    return 0
fi

require_helm_major_version 4
require_empty_index "$MANIFESTS_DIRECTORY"
create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"
copy_manifests "${SOURCE_DIRECTORY}/${REPOSITORY_DIRECTORY}/${SOURCE_MANIFESTS_PATH}" "${MANIFESTS_DIRECTORY}/${DESTINATION_MANIFESTS_PATH}"
apply_katib_mysql_patch "$MANIFESTS_DIRECTORY"
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
update_katib_helm_chart
validate_katib_helm_chart
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" \
  "${DESTINATION_MANIFESTS_PATH}" \
  "${MYSQL_PATCH_PATH}" \
  "${HELM_CHART_PATH}/Chart.yaml" \
  "${HELM_CHART_PATH}/kustomize/kustomization.yaml" \
  "${HELM_CHART_PATH}/manifests" \
  "${SCRIPT_DIRECTORY}/generate-katib-helm-manifests.py" \
  "${SCRIPT_DIRECTORY}/synchronize-katib-manifests.sh" \
  "README.md"
echo "Synchronization completed successfully."
