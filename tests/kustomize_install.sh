#!/bin/bash
set -euxo pipefail

KUSTOMIZE_VERSION="v5.8.1"
USER_BINARY_DIRECTORY="$HOME/.local/bin"

if [[ "${GITHUB_ACTIONS:-false}" == "true" ]]; then
    USER_BINARY_DIRECTORY="/tmp/usr/local/bin"
fi

mkdir -p "${USER_BINARY_DIRECTORY}"
export PATH="${USER_BINARY_DIRECTORY}:${PATH}"

echo "Install Kustomize ..."
{
    KUSTOMIZE_ASSET="kustomize_${KUSTOMIZE_VERSION}_linux_amd64.tar.gz"
    curl --fail --show-error --silent --location --retry 3 --retry-delay 2 --retry-all-errors --remote-name "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F${KUSTOMIZE_VERSION}/${KUSTOMIZE_ASSET}"
    curl --fail --show-error --silent --location --retry 3 --retry-delay 2 --retry-all-errors "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F${KUSTOMIZE_VERSION}/checksums.txt" | grep "  ${KUSTOMIZE_ASSET}$" > checksums.txt
    if [ "$(wc -l < checksums.txt)" -ne 1 ]; then
       echo "Failed to verify Kustomize checksums: expected exactly one checksum entry for ${KUSTOMIZE_ASSET}"
       exit 1
    fi
    if ! sha256sum --check checksums.txt; then
       echo "Failed to verify Kustomize checksums"
       exit 1
    fi
    tar -xzvf "${KUSTOMIZE_ASSET}"
    chmod a+x kustomize
    mv kustomize "${USER_BINARY_DIRECTORY}/kustomize"
} || { echo "Failed to install Kustomize"; exit 1; }
