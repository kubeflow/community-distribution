#!/bin/bash
set -euxo pipefail

KIND_VERSION="v0.31.0"
KIND_NODE_IMAGE="kindest/node:v1.35.0@sha256:452d707d4862f52530247495d180205e029056831160e22870e37e3f6c1ac31f"
KUSTOMIZE_VERSION="v5.8.1" # Replace with v5.8.0 if v5.8.1 is unavailable
USER_BINARY_DIRECTORY="$HOME/.local/bin"

if [[ "${GITHUB_ACTIONS:-false}" == "true" ]]; then
    USER_BINARY_DIRECTORY="/tmp/usr/local/bin"
fi

mkdir -p "${USER_BINARY_DIRECTORY}"
export PATH="${USER_BINARY_DIRECTORY}:${PATH}"

echo "Install KinD..."

# https://github.com/nektos/act
# This conditional helps running GitHub Workflows through
if [[ "${GITHUB_ACTIONS:-false}" == "true" ]]; then
    echo "Running in GitHub Actions: Optimizing environment..."
    sudo swapoff -a
    if [ -e /swapfile ]; then
        sudo rm -f /swapfile
        sudo mkdir -p /tmp/etcd
        sudo mount -t tmpfs tmpfs /tmp/etcd
    fi
fi

{
    curl -Lo ./kind-linux-amd64 https://kind.sigs.k8s.io/dl/$KIND_VERSION/kind-linux-amd64
    curl -Lo ./kind-linux-amd64.sha256sum https://kind.sigs.k8s.io/dl/$KIND_VERSION/kind-linux-amd64.sha256sum
    if ! sha256sum --check kind-linux-amd64.sha256sum; then
       echo "Failed to verify KinD checksums"
       exit 1
    fi
    chmod +x ./kind-linux-amd64
    mv kind-linux-amd64 "${USER_BINARY_DIRECTORY}/kind"
} || { echo "Failed to install KinD"; exit 1; }

echo "Creating KinD cluster ..."
echo "
apiVersion: kind.x-k8s.io/v1alpha4
kind: Cluster
# This is needed in order to support projected volumes with service account tokens.
# See: https://kubernetes.slack.com/archives/CEKK1KTN2/p1600268272383600
kubeadmConfigPatches:
  - |
    apiVersion: kubeadm.k8s.io/v1beta3
    kind: ClusterConfiguration
    metadata:
      name: config
    apiServer:
      extraArgs:
        \"service-account-issuer\": \"https://kubernetes.default.svc\"
        \"service-account-signing-key-file\": \"/etc/kubernetes/pki/sa.key\"
nodes:
- role: control-plane
  image: ${KIND_NODE_IMAGE}
- role: worker
  image: ${KIND_NODE_IMAGE}
- role: worker
  image: ${KIND_NODE_IMAGE}
" | kind create cluster --name kubeflow --config - --wait 120s

echo "Install kubectl ..."
{
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    chmod +x ./kubectl
    mv kubectl "${USER_BINARY_DIRECTORY}/kubectl"
} || { echo "Failed to install kubectl"; exit 1; }

kubectl cluster-info

echo "Install Kustomize ..."

{
    KUSTOMIZE_ASSET="kustomize_${KUSTOMIZE_VERSION}_linux_amd64.tar.gz"
    DOWNLOAD_URL="https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F${KUSTOMIZE_VERSION}/${KUSTOMIZE_ASSET}"

    # Retry logic for downloading Kustomize
    MAX_RETRIES=3
    COUNT=0

    while [ "$COUNT" -lt "$MAX_RETRIES" ]; do
        echo "Attempting to download Kustomize version ${KUSTOMIZE_VERSION} (Attempt $((COUNT+1))/${MAX_RETRIES})..."
        if curl --fail --silent --show-error --location --remote-name "${DOWNLOAD_URL}"; then
            break
        fi
        COUNT=$((COUNT + 1))
        sleep 5
    done

    if [ "$COUNT" -eq "$MAX_RETRIES" ]; then
        echo "Failed to download Kustomize after $MAX_RETRIES attempts. Falling back to version v5.8.0."
        KUSTOMIZE_VERSION="v5.8.0"
        KUSTOMIZE_ASSET="kustomize_${KUSTOMIZE_VERSION}_linux_amd64.tar.gz"
        DOWNLOAD_URL="https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F${KUSTOMIZE_VERSION}/${KUSTOMIZE_ASSET}"
        
        curl --fail --silent --show-error --location --remote-name "${DOWNLOAD_URL}"
    fi

    # Verify checksums
    curl --fail --silent --show-error --location "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F${KUSTOMIZE_VERSION}/checksums.txt" | grep "  ${KUSTOMIZE_ASSET}$" > checksums.txt
    if [ "$(wc -l < checksums.txt)" -ne 1 ]; then
       echo "Failed to verify Kustomize checksums: expected exactly one checksum entry for ${KUSTOMIZE_ASSET}"
       exit 1
    fi
    if ! sha256sum --check checksums.txt; then
       echo "Failed to verify Kustomize checksums"
       exit 1
    fi

    # Extract and install Kustomize
    tar -xzvf "${KUSTOMIZE_ASSET}"
    chmod a+x kustomize
    mv kustomize "${USER_BINARY_DIRECTORY}/kustomize"
} || { echo "Failed to install Kustomize"; exit 1; }

# Free disk space in GitHub Actions to reduce "no space left on device" failures.
if [[ "${GITHUB_ACTIONS:-false}" == "true" ]]; then
    echo "=== Disk usage before cleanup ==="
    df -h

    echo "=== Freeing up disk space ==="

    sudo rm -rf /usr/share/dotnet
    sudo rm -rf /opt/ghc
    sudo rm -rf /usr/local/share/boost
    sudo rm -rf /usr/local/lib/android
    sudo rm -rf /usr/local/.ghcup
    sudo rm -rf /usr/share/swift

    sudo rm -rf /opt/hostedtoolcache/CodeQL || true
    sudo rm -rf /opt/hostedtoolcache/Java_* || true
    sudo rm -rf /opt/hostedtoolcache/Ruby || true
    sudo rm -rf /opt/hostedtoolcache/PyPy || true
    sudo rm -rf /opt/hostedtoolcache/boost || true

    sudo apt-get autoclean

    docker system prune -af --volumes
    docker image prune -af

    echo "=== Final disk usage ==="
    df -h
fi