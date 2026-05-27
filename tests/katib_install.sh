#!/bin/bash
set -euxo pipefail

KATIB_CI_OVERLAY=$(mktemp -d .katib-ci-overlay.XXXXXX)
trap 'rm -rf "$KATIB_CI_OVERLAY"' EXIT

awk '
  { print }
  $0 == "    webhookPort: 8443" { print "    injectSecurityContext: true" }
' applications/katib/upstream/installs/katib-cert-manager/katib-config.yaml > "$KATIB_CI_OVERLAY/katib-config.yaml"

cat > "$KATIB_CI_OVERLAY/kustomization.yaml" <<'EOF'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
- ../applications/katib/upstream/installs/katib-with-kubeflow
generatorOptions:
  disableNameSuffixHash: true
configMapGenerator:
- name: katib-config
  behavior: replace
  files:
  - katib-config.yaml
EOF

kustomize build "$KATIB_CI_OVERLAY" | kubectl apply -f -
kubectl rollout status deployment/katib-controller -n kubeflow --timeout=300s
kubectl wait --for=condition=Available deployment/katib-controller -n kubeflow --timeout=300s

kubectl wait --for=condition=Available deployment/katib-mysql -n kubeflow --timeout=300s

kubectl label namespace $KF_PROFILE katib.kubeflow.org/metrics-collector-injection=enabled --overwrite
