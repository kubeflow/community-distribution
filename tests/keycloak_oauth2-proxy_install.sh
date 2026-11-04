#!/bin/bash
set -euxo pipefail

echo "Installing oauth2-proxy connected directly to Keycloak ..."
kustomize build tests/keycloak/oauth2-proxy | kubectl apply -f -

kubectl wait --for=condition=Ready pod -l 'app.kubernetes.io/name=oauth2-proxy' --timeout=180s -n oauth2-proxy
kubectl wait --for=condition=Ready pod -l 'app.kubernetes.io/name=cluster-jwks-proxy' --timeout=180s -n istio-system
kubectl wait --for=condition=Available deployment -n oauth2-proxy oauth2-proxy --timeout=180s
