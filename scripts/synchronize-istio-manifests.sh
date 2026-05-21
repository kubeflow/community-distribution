#!/usr/bin/env bash
# This script helps to create a PR to update the unified Istio manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="istio"
REPOSITORY_NAME="istio/istio"
COMMIT="1.30.0"
PREVIOUS_COMMIT="1.30.0"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/kubeflow-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${COMMIT?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
ISTIO_DIRECTORY=$MANIFESTS_DIRECTORY/common/${COMPONENT_NAME}
create_branch "$BRANCH_NAME"
mkdir -p "$SOURCE_DIRECTORY"
cd "$SOURCE_DIRECTORY"
if [ ! -d "istio-${COMMIT}" ]; then
    wget "https://github.com/${REPOSITORY_NAME}/releases/download/${COMMIT}/istio-${COMMIT}-linux-amd64.tar.gz"
    tar xvfz istio-${COMMIT}-linux-amd64.tar.gz
fi
ISTIOCTL="${SOURCE_DIRECTORY}/istio-${COMMIT}/bin/istioctl"
cd "$ISTIO_DIRECTORY"
sed -i "s/tag: .*/tag: $COMMIT/" "$ISTIO_DIRECTORY/profile.yaml"
$ISTIOCTL manifest generate -f profile.yaml -f profile-overlay.yaml \
  --set components.cni.enabled=true \
  --set components.cni.namespace=kube-system > dump.yaml
./split-istio-packages -f dump.yaml
mv $ISTIO_DIRECTORY/crd.yaml $ISTIO_DIRECTORY/istio-crds/base/
mv $ISTIO_DIRECTORY/install.yaml $ISTIO_DIRECTORY/istio-install/base/
mv $ISTIO_DIRECTORY/cluster-local-gateway.yaml $ISTIO_DIRECTORY/cluster-local-gateway/base/
rm dump.yaml
$ISTIOCTL manifest generate -f profile.yaml -f profile-overlay.yaml \
  --set components.cni.enabled=true \
  --set components.ztunnel.enabled=true > dump-ztunnel.yaml
./split-istio-packages -f dump-ztunnel.yaml
mv $ISTIO_DIRECTORY/ztunnel.yaml $ISTIO_DIRECTORY/istio-install/components/ambient-mode/
rm dump-ztunnel.yaml crd.yaml install.yaml cluster-local-gateway.yaml
sed -i "s/\"tag\": \".*\"/\"tag\": \"$COMMIT\"/" "$ISTIO_DIRECTORY/istio-install/base/patches/istio-sidecar-injector-patch.yaml"
# Normalize all remaining Istio version references from PREVIOUS_COMMIT to COMMIT.
# This catches any version strings that istioctl generates using the previous release
# (e.g. image tags, helm chart labels). Update PREVIOUS_COMMIT when bumping COMMIT.
find "$ISTIO_DIRECTORY" -name "*.yaml" | xargs sed -i \
  -e "s/${PREVIOUS_COMMIT}/$COMMIT/g"
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/releases/tag/.*)"
DESTINATION_TEXT="\[$COMMIT\](https://github.com/${REPOSITORY_NAME}/releases/tag/$COMMIT)"
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${COMMIT}" "$MANIFESTS_DIRECTORY"
echo "Synchronization completed successfully."
