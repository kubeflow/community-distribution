#!/usr/bin/env bash
# Generate the MLflow Kustomize base from the canonical Helm chart.
SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
source "${SCRIPT_DIRECTORY}/library.sh"
setup_error_handling

COMPONENT_NAME="mlflow"
REPOSITORY_NAME="kubeflow/mlflow-integration"
REPOSITORY_URL="https://github.com/${REPOSITORY_NAME}.git"
COMMIT="d276153b84844c076d92c74519a3c405936220de"
REPOSITORY_DIRECTORY="mlflow-integration"
SOURCE_DIRECTORY=${SOURCE_DIRECTORY:=/tmp/kubeflow-${COMPONENT_NAME}}
BRANCH_NAME=${BRANCH_NAME:=synchronize-kubeflow-${COMPONENT_NAME}-manifests-${COMMIT}}
MANIFESTS_DIRECTORY=$(dirname "$SCRIPT_DIRECTORY")
CHART_DIRECTORY="${SOURCE_DIRECTORY}/${REPOSITORY_DIRECTORY}/charts/mlflow"
VALUES_FILE="${MANIFESTS_DIRECTORY}/applications/mlflow/values-kubeflow.yaml"
DESTINATION_DIRECTORY="${MANIFESTS_DIRECTORY}/applications/mlflow/upstream/base"

create_branch "$BRANCH_NAME"
clone_and_checkout "$SOURCE_DIRECTORY" "$REPOSITORY_URL" "$REPOSITORY_DIRECTORY" "$COMMIT"

rm -rf "$DESTINATION_DIRECTORY"
mkdir -p "$DESTINATION_DIRECTORY"
helm lint "$CHART_DIRECTORY" --values "$VALUES_FILE"
helm template mlflow "$CHART_DIRECTORY" \
  --namespace kubeflow \
  --values "$VALUES_FILE" \
  >"${DESTINATION_DIRECTORY}/resources.yaml"

cat >"${DESTINATION_DIRECTORY}/kustomization.yaml" <<'EOF'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
  - resources.yaml
EOF

kustomize build "$DESTINATION_DIRECTORY" >/dev/null

commit_changes "$MANIFESTS_DIRECTORY" \
  "Synchronize ${REPOSITORY_NAME} manifests from ${COMMIT}" \
  "applications/mlflow/upstream" \
  "applications/mlflow/values-kubeflow.yaml" \
  "scripts/synchronize-mlflow-manifests.sh"
echo "Synchronization completed successfully."
