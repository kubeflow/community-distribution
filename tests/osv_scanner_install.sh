#!/bin/bash
set -euxo pipefail

OSV_SCANNER_VERSION="v2.7.0"
OSV_SCANNER_ASSET="osv-scanner_linux_amd64"
OSV_SCANNER_SHA256="160c6253e2922e9e0a6a9771c5c4c40a4b3c6090b34a3cdd5e80c96cc2e4218b"
USER_BINARY_DIRECTORY="$HOME/.local/bin"

if [[ "${GITHUB_ACTIONS:-false}" == "true" ]]; then
    USER_BINARY_DIRECTORY="/tmp/usr/local/bin"
fi

mkdir -p "${USER_BINARY_DIRECTORY}"
export PATH="${USER_BINARY_DIRECTORY}:${PATH}"

echo "Install osv-scanner ..."
{
    curl --fail --show-error --silent --location \
      --output "${USER_BINARY_DIRECTORY}/osv-scanner" \
      "https://github.com/google/osv-scanner/releases/download/${OSV_SCANNER_VERSION}/${OSV_SCANNER_ASSET}"
    echo "${OSV_SCANNER_SHA256}  ${USER_BINARY_DIRECTORY}/osv-scanner" | sha256sum --check
    chmod a+x "${USER_BINARY_DIRECTORY}/osv-scanner"
} || { echo "Failed to install osv-scanner"; exit 1; }

echo "osv-scanner installed successfully"
osv-scanner --version
