#!/bin/bash
set -euxo pipefail

OSV_SCANNER_VERSION="v2.3.8"
OSV_SCANNER_ASSET="osv-scanner_linux_amd64"
OSV_SCANNER_SHA256="bc98e15319ed0d515e3f9235287ba53cdc5535d576d24fd573978ecfe9ab92dc"
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
