#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(dirname "$SCRIPT_DIRECTORY")"
MANIFEST_DIRECTORY="$REPOSITORY_ROOT/applications/mlflow/overlays/kubeflow"

# A source-image test is explicit; ordinary installations still use the release.
if [[ -n "${MLFLOW_TEST_IMAGE:-}" ]]; then
  MANIFEST_DIRECTORY="$(mktemp -d "$REPOSITORY_ROOT/.mlflow-install.XXXXXX")"
  trap 'rm -rf "$MANIFEST_DIRECTORY"' EXIT
  cat > "$MANIFEST_DIRECTORY/kustomization.yaml" <<'EOF'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../applications/mlflow/overlays/kubeflow
patches:
  - target:
      kind: Deployment
      name: mlflow
    patch: |-
      - op: replace
        path: /spec/template/spec/containers/0/imagePullPolicy
        value: Never
EOF
  (
    cd "$MANIFEST_DIRECTORY"
    kustomize edit set image "ghcr.io/kubeflow/mlflow-integration=$MLFLOW_TEST_IMAGE"
  )
  echo "Testing preloaded MLflow source image: $MLFLOW_TEST_IMAGE"
fi

echo "Installing MLflow..."
kustomize build "$MANIFEST_DIRECTORY" \
  | kubectl apply --server-side --force-conflicts -f -

if ! kubectl rollout status deployment/mlflow --namespace kubeflow --timeout=300s; then
  kubectl get pods,persistentvolumeclaims --namespace kubeflow \
    --selector app.kubernetes.io/name=mlflow --output=wide || true
  kubectl describe pods --namespace kubeflow \
    --selector app.kubernetes.io/name=mlflow || true
  kubectl logs --namespace kubeflow --selector app.kubernetes.io/name=mlflow \
    --all-containers=true --prefix --tail=100 || true
  kubectl logs --namespace kubeflow --selector app.kubernetes.io/name=mlflow \
    --all-containers=true --prefix --tail=100 --previous || true
  exit 1
fi

kubectl get deployment,service,persistentvolumeclaim \
  --namespace kubeflow \
  --selector app.kubernetes.io/name=mlflow
