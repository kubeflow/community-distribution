#!/usr/bin/env bash
# This script helps to create a PR to update the Knative manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
require_helm_major_version 4
COMPONENT_NAME="knative"
REPOSITORY_NAME="knative"
KN_SERVING_RELEASE="v1.23.0"
KN_EXTENSION_RELEASE="v1.23.0"
KN_EVENTING_RELEASE="v1.23.0"
COMMIT="${KN_SERVING_RELEASE}/${KN_EVENTING_RELEASE}"
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${KN_SERVING_RELEASE?}}
MANIFESTS_DIRECTORY=$(dirname "$SCRIPT_DIRECTORY")
DESTINATION_DIRECTORY=$MANIFESTS_DIRECTORY/common/${COMPONENT_NAME}
create_branch "$BRANCH_NAME"
if [ -d "$DESTINATION_DIRECTORY" ]; then
    rm -rf "$DESTINATION_DIRECTORY/knative-serving/base/upstream"
    rm -f "$DESTINATION_DIRECTORY/knative-serving-post-install-jobs/base/serving-post-install-jobs.yaml"
    rm -rf "$DESTINATION_DIRECTORY/knative-eventing/base/upstream"
    rm -f "$DESTINATION_DIRECTORY/knative-eventing-post-install-jobs/base/eventing-post-install.yaml"
fi
mkdir -p "$DESTINATION_DIRECTORY/knative-serving/base/upstream"
mkdir -p "$DESTINATION_DIRECTORY/knative-serving-post-install-jobs/base"
mkdir -p "$DESTINATION_DIRECTORY/knative-eventing/base/upstream"
mkdir -p "$DESTINATION_DIRECTORY/knative-eventing-post-install-jobs/base"
wget -O "$DESTINATION_DIRECTORY/knative-serving/base/upstream/serving-core.yaml" "https://github.com/knative/serving/releases/download/knative-$KN_SERVING_RELEASE/serving-core.yaml"
wget -O "$DESTINATION_DIRECTORY/knative-serving/base/upstream/net-istio.yaml" "https://github.com/knative-extensions/net-istio/releases/download/knative-$KN_EXTENSION_RELEASE/net-istio.yaml"
wget -O "$DESTINATION_DIRECTORY/knative-serving-post-install-jobs/base/serving-post-install-jobs.yaml" "https://github.com/knative/serving/releases/download/knative-$KN_SERVING_RELEASE/serving-post-install-jobs.yaml"
yq eval -i '... comments=""' "$DESTINATION_DIRECTORY/knative-serving/base/upstream/serving-core.yaml"
yq eval -i '... comments=""' "$DESTINATION_DIRECTORY/knative-serving/base/upstream/net-istio.yaml"
yq eval -i '... comments=""' "$DESTINATION_DIRECTORY/knative-serving-post-install-jobs/base/serving-post-install-jobs.yaml"
yq eval -i 'select(.kind == "Job" and .metadata.generateName == "storage-version-migration-serving-") | .metadata.name = "storage-version-migration-serving"' "$DESTINATION_DIRECTORY/knative-serving-post-install-jobs/base/serving-post-install-jobs.yaml"
wget -O "$DESTINATION_DIRECTORY/knative-eventing/base/upstream/eventing-core.yaml" "https://github.com/knative/eventing/releases/download/knative-$KN_EVENTING_RELEASE/eventing-core.yaml"
wget -O "$DESTINATION_DIRECTORY/knative-eventing/base/upstream/in-memory-channel.yaml" "https://github.com/knative/eventing/releases/download/knative-$KN_EVENTING_RELEASE/in-memory-channel.yaml"
wget -O "$DESTINATION_DIRECTORY/knative-eventing/base/upstream/mt-channel-broker.yaml" "https://github.com/knative/eventing/releases/download/knative-$KN_EVENTING_RELEASE/mt-channel-broker.yaml"
wget -O "$DESTINATION_DIRECTORY/knative-eventing-post-install-jobs/base/eventing-post-install.yaml" "https://github.com/knative/eventing/releases/download/knative-$KN_EVENTING_RELEASE/eventing-post-install.yaml"
yq eval -i '... comments=""' "$DESTINATION_DIRECTORY/knative-eventing/base/upstream/eventing-core.yaml"
yq eval -i '... comments=""' "$DESTINATION_DIRECTORY/knative-eventing/base/upstream/in-memory-channel.yaml"
yq eval -i '... comments=""' "$DESTINATION_DIRECTORY/knative-eventing/base/upstream/mt-channel-broker.yaml"
yq eval -i '... comments=""' "$DESTINATION_DIRECTORY/knative-eventing-post-install-jobs/base/eventing-post-install.yaml"
yq eval -i 'select(.kind == "Job" and .metadata.generateName == "storage-version-migration-eventing-") | .metadata.name = "storage-version-migration-eventing"' "$DESTINATION_DIRECTORY/knative-eventing-post-install-jobs/base/eventing-post-install.yaml"
replace_in_file() {
  local SOURCE_TEXT=$1
  local DESTINATION_TEXT=$2
  local FILE=$3
  sed -i "s|$SOURCE_TEXT|$DESTINATION_TEXT|g" "$FILE"
}
replace_in_file \
  "\[.*\](https://github.com/knative/serving/releases/tag/knative-.*) <" \
  "\[$KN_SERVING_RELEASE\](https://github.com/knative/serving/releases/tag/knative-$KN_SERVING_RELEASE) <" \
  "${MANIFESTS_DIRECTORY}/README.md"
replace_in_file \
  "> \[.*\](https://github.com/knative/eventing/releases/tag/knative-.*)" \
  "> \[$KN_EVENTING_RELEASE\](https://github.com/knative/eventing/releases/tag/knative-$KN_EVENTING_RELEASE)" \
  "${MANIFESTS_DIRECTORY}/README.md"
replace_in_file \
  "\[Knative serving (v.*)\](https://github.com/knative/serving/releases/tag/knative-v.*)" \
  "\[Knative serving ($KN_SERVING_RELEASE)\](https://github.com/knative/serving/releases/tag/knative-$KN_SERVING_RELEASE)" \
  "$DESTINATION_DIRECTORY/README.md"
replace_in_file \
  "\[Knative ingress controller for Istio (v.*)\](https://github.com/knative-extensions/net-istio/releases/tag/knative-v.*)" \
  "\[Knative ingress controller for Istio ($KN_EXTENSION_RELEASE)\](https://github.com/knative-extensions/net-istio/releases/tag/knative-$KN_EXTENSION_RELEASE)" \
  "$DESTINATION_DIRECTORY/README.md"
replace_in_file \
  "The manifests for Knative Eventing are based off the \[v.* release\](https://github.com/knative/eventing/releases/tag/knative-v.*)" \
  "The manifests for Knative Eventing are based off the \[$KN_EVENTING_RELEASE release\](https://github.com/knative/eventing/releases/tag/knative-$KN_EVENTING_RELEASE)" \
  "$DESTINATION_DIRECTORY/README.md"
# Chart metadata comes from the same pinned bundles, not a second image pin.
serving_chart="$DESTINATION_DIRECTORY/knative-serving/helm"
update_helm_chart_application_version "$serving_chart/Chart.yaml" "${KN_SERVING_RELEASE#v}"
queue_proxy_image=$(yq eval 'select(.kind == "Image" and .metadata.name == "queue-proxy") | .spec.image' \
  "$DESTINATION_DIRECTORY/knative-serving/base/upstream/serving-core.yaml")
if [[ ! "$queue_proxy_image" =~ ^[^[:space:]]+@sha256:[a-f0-9]{64}$ ]]; then
  echo "Expected exactly one digest-pinned queue-proxy Image in the Serving bundle" >&2
  exit 1
fi
QUEUE_PROXY_IMAGE="$queue_proxy_image" yq eval -i \
  '.annotations."kubeflow.org/queue-proxy-image" = strenv(QUEUE_PROXY_IMAGE)' \
  "$serving_chart/Chart.yaml"
python3 "$SCRIPT_DIRECTORY/generate-knative-serving-helm-manifests.py" --repository-root "$MANIFESTS_DIRECTORY"
helm lint "$serving_chart" --namespace kubeflow

eventing_chart="$DESTINATION_DIRECTORY/knative-eventing/helm"
update_helm_chart_application_version "$eventing_chart/Chart.yaml" "${KN_EVENTING_RELEASE#v}"
python3 "$SCRIPT_DIRECTORY/generate-knative-eventing-helm-manifests.py" --repository-root "$MANIFESTS_DIRECTORY"
helm lint "$eventing_chart" --namespace kubeflow

# Only imported bundles, derived metadata/payloads and synchronized version tables
# are generated outputs. Do not stage hand-written chart templates or other work.
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" \
  "common/knative/knative-serving/base/upstream" \
  "common/knative/knative-serving-post-install-jobs/base/serving-post-install-jobs.yaml" \
  "common/knative/knative-eventing/base/upstream" \
  "common/knative/knative-eventing-post-install-jobs/base/eventing-post-install.yaml" \
  "common/knative/knative-serving/helm/Chart.yaml" \
  "common/knative/knative-serving/helm/manifests" \
  "common/knative/knative-eventing/helm/Chart.yaml" \
  "common/knative/knative-eventing/helm/manifests" \
  "common/knative/README.md" \
  "README.md"
echo "Synchronization completed successfully."
