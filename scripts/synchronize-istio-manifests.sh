#!/usr/bin/env bash
# This script helps to create a PR to update the unified Istio manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="istio"
REPOSITORY_NAME="istio/istio"
ISTIO_VERSION="1.30.2"
PREVIOUS_ISTIO_VERSION=${PREVIOUS_ISTIO_VERSION:=$(awk -F. '{print $1 "." $2 "." ($3-1)}' <<< "$ISTIO_VERSION")}
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/kubeflow-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${ISTIO_VERSION?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
ISTIO_DIRECTORY=$MANIFESTS_DIRECTORY/common/${COMPONENT_NAME}
create_branch "$BRANCH_NAME"
mkdir -p "$SOURCE_DIRECTORY"
cd "$SOURCE_DIRECTORY"
if [ ! -d "istio-${ISTIO_VERSION}" ]; then
    wget "https://github.com/${REPOSITORY_NAME}/releases/download/${ISTIO_VERSION}/istio-${ISTIO_VERSION}-linux-amd64.tar.gz"
    tar xvfz istio-${ISTIO_VERSION}-linux-amd64.tar.gz
fi
ISTIOCTL="${SOURCE_DIRECTORY}/istio-${ISTIO_VERSION}/bin/istioctl"
cd "$ISTIO_DIRECTORY"
sed -i "s/tag: .*/tag: $ISTIO_VERSION/" "$ISTIO_DIRECTORY/profile.yaml"
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
sed -i "s/\"tag\": \".*\"/\"tag\": \"$ISTIO_VERSION\"/" "$ISTIO_DIRECTORY/istio-install/base/patches/istio-sidecar-injector-patch.yaml"
# Normalize all remaining Istio version references from PREVIOUS_ISTIO_VERSION to ISTIO_VERSION.
# This catches any version strings that istioctl generates using the previous release
# (e.g. image tags, helm chart labels). Update PREVIOUS_ISTIO_VERSION when bumping ISTIO_VERSION.
find "$ISTIO_DIRECTORY" -name "*.yaml" -exec sed -i \
  -e "s/${PREVIOUS_ISTIO_VERSION}/$ISTIO_VERSION/g" {} +
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/releases/tag/.*)"
DESTINATION_TEXT="\[$ISTIO_VERSION\](https://github.com/${REPOSITORY_NAME}/releases/tag/$ISTIO_VERSION)"
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${ISTIO_VERSION}" "$MANIFESTS_DIRECTORY"
echo "Synchronization completed successfully."
