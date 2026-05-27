#!/bin/bash
set -euxo pipefail

KATIB_CI_OVERLAY=$(mktemp -d .katib-ci-overlay.XXXXXX)
trap 'rm -rf "$KATIB_CI_OVERLAY"' EXIT

cat > "$KATIB_CI_OVERLAY/kustomization.yaml" <<'EOF'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
- ../applications/katib/upstream/installs/katib-with-kubeflow
patches:
- target:
    group: apps
    version: v1
    kind: Deployment
    name: katib-controller
  patch: |-
    - op: add
      path: /spec/template/spec/containers/0/args/-
      value: --inject-security-context=true
EOF

kustomize build "$KATIB_CI_OVERLAY" | kubectl apply -f -
kubectl rollout status deployment/katib-controller -n kubeflow --timeout=300s
kubectl wait --for=condition=Available deployment/katib-controller -n kubeflow --timeout=300s

kubectl wait --for=condition=Available deployment/katib-mysql -n kubeflow --timeout=300s

kubectl label namespace $KF_PROFILE katib.kubeflow.org/metrics-collector-injection=enabled --overwrite
