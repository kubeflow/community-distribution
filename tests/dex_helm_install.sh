#!/usr/bin/env bash
# Helm counterpart of tests/dex_install.sh, proven equivalent to
# common/dex/overlays/oauth2-proxy by the dex comparison scenario. The ci
# values carry the parity fixture credentials the end-to-end login test uses.
set -euxo pipefail
helm install dex common/dex/helm \
  --namespace auth \
  --values common/dex/helm/ci/values-oauth2-proxy.yaml \
  --wait --timeout 5m
kubectl wait --for=condition=Ready pods --all --timeout=180s -n auth
