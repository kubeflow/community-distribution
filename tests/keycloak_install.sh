#!/bin/bash
set -euxo pipefail

echo "Installing Keycloak ..."
kustomize build tests/keycloak | kubectl apply -f -
kubectl -n keycloak rollout status deployment/keycloak --timeout=300s

# The test runner reaches Keycloak at the same address as the Pods do, so the
# browser redirects and the token issuer use one identical URL.
echo "127.0.0.1 keycloak.keycloak.svc.cluster.local" | sudo tee -a /etc/hosts
nohup kubectl port-forward -n keycloak svc/keycloak 8081:8081 &
timeout 60s bash -c 'until curl -sf http://keycloak.keycloak.svc.cluster.local:8081/realms/kubeflow/.well-known/openid-configuration > /dev/null; do sleep 2; done'
