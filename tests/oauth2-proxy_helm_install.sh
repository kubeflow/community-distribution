#!/usr/bin/env bash
# Helm counterpart of tests/oauth2-proxy_install.sh, proven equivalent to
# common/oauth2-proxy/overlays/m2m-dex-and-kind by the comparison scenario.
set -euxo pipefail
echo "Installing oauth2-proxy with Helm..."
helm install oauth2-proxy common/oauth2-proxy/helm \
  --namespace oauth2-proxy \
  --values common/oauth2-proxy/helm/ci/values-m2m-dex-and-kind.yaml \
  --wait --timeout 5m
kubectl wait --for=condition=Ready pod -l 'app.kubernetes.io/name=oauth2-proxy' --timeout=180s -n oauth2-proxy
kubectl wait --for=condition=Ready pod -l 'app.kubernetes.io/name=cluster-jwks-proxy' --timeout=180s -n istio-system
