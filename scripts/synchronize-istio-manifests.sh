#!/usr/bin/env bash
# This script helps to create a PR to update the unified Istio manifests
SCRIPT_DIRECTORY=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling
COMPONENT_NAME="istio"
REPOSITORY_NAME="istio/istio"
ISTIO_CURRENT_VERSION="1.30.2"
ISTIO_PREVIOUS_VERSION=${ISTIO_PREVIOUS_VERSION:-}
if [ -z "$ISTIO_PREVIOUS_VERSION" ]; then
  IFS='.' read -r major minor patch <<< "$ISTIO_CURRENT_VERSION"
  if [ "$patch" -gt 0 ]; then
    ISTIO_PREVIOUS_VERSION="${major}.${minor}.$((patch - 1))"
  else
    echo "ERROR: Unable to infer previous Istio version from ${ISTIO_CURRENT_VERSION}. Set ISTIO_PREVIOUS_VERSION explicitly."
    exit 1
  fi
fi
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/kubeflow-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-${COMPONENT_NAME}-manifests-${ISTIO_CURRENT_VERSION?}}
MANIFESTS_DIRECTORY=$(dirname $SCRIPT_DIRECTORY)
ISTIO_DIRECTORY=$MANIFESTS_DIRECTORY/common/${COMPONENT_NAME}
create_branch "$BRANCH_NAME"
mkdir -p "$SOURCE_DIRECTORY"
cd "$SOURCE_DIRECTORY"
if [ ! -d "istio-${ISTIO_CURRENT_VERSION}" ]; then
    wget "https://github.com/${REPOSITORY_NAME}/releases/download/${ISTIO_CURRENT_VERSION}/istio-${ISTIO_CURRENT_VERSION}-linux-amd64.tar.gz"
    tar xvfz istio-${ISTIO_CURRENT_VERSION}-linux-amd64.tar.gz
fi
ISTIOCTL="${SOURCE_DIRECTORY}/istio-${ISTIO_CURRENT_VERSION}/bin/istioctl"
cd "$ISTIO_DIRECTORY"
sed -i "s/tag: .*/tag: $ISTIO_CURRENT_VERSION/" "$ISTIO_DIRECTORY/profile.yaml"
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
sed -i "s/\"tag\": \".*\"/\"tag\": \"$ISTIO_CURRENT_VERSION\"/" "$ISTIO_DIRECTORY/istio-install/base/patches/istio-sidecar-injector-patch.yaml"
# Normalize all remaining Istio version references from ISTIO_PREVIOUS_VERSION to ISTIO_CURRENT_VERSION.
# This catches any version strings that istioctl generates using the previous release
# (e.g. image tags, helm chart labels). Update ISTIO_PREVIOUS_VERSION when needed.
if [ -z "$ISTIO_PREVIOUS_VERSION" ]; then
  echo "ERROR: ISTIO_PREVIOUS_VERSION cannot be empty."
  exit 1
fi
find "$ISTIO_DIRECTORY" -name "*.yaml" -exec sed -i \
  -e "s/${ISTIO_PREVIOUS_VERSION}/$ISTIO_CURRENT_VERSION/g" {} +
SOURCE_TEXT="\[.*\](https://github.com/${REPOSITORY_NAME}/releases/tag/.*)"
DESTINATION_TEXT="\[$ISTIO_CURRENT_VERSION\](https://github.com/${REPOSITORY_NAME}/releases/tag/$ISTIO_CURRENT_VERSION)"
update_readme "$MANIFESTS_DIRECTORY" "$SOURCE_TEXT" "$DESTINATION_TEXT"
commit_changes "$MANIFESTS_DIRECTORY" "Update ${REPOSITORY_NAME} manifests from ${ISTIO_CURRENT_VERSION}" "$MANIFESTS_DIRECTORY"
echo "Synchronization completed successfully."
