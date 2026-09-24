#!/usr/bin/env bash

set -euo pipefail

PIPELINES_SCENARIO="${1:-}"
SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIRECTORY="$(dirname "$SCRIPT_DIRECTORY")"
CHART_DIRECTORY="${ROOT_DIRECTORY}/applications/pipeline/helm"
RELEASE_NAME="kubeflow-pipelines"
# The chart guards its release namespace. Every namespaced resource it renders
# declares namespace: kubeflow, so the release lives there too.
RELEASE_NAMESPACE="kubeflow"
WORKLOAD_NAMESPACE="kubeflow"

if [[ -z "$PIPELINES_SCENARIO" ]]; then
    echo "Usage: pipelines_helm_install.sh <scenario>" >&2
    echo "Supported scenarios: platform-database, platform-k8s-native" >&2
    exit 2
fi

case "$PIPELINES_SCENARIO" in
    "platform-database"|"platform-k8s-native")
        ;;
    *)
        echo "Unsupported Kubeflow Pipelines scenario: $PIPELINES_SCENARIO" >&2
        echo "Supported scenarios: platform-database, platform-k8s-native" >&2
        exit 2
        ;;
esac

SCENARIO_VALUES_FILE="${CHART_DIRECTORY}/ci/values-${PIPELINES_SCENARIO}.yaml"

helm install "$RELEASE_NAME" "$CHART_DIRECTORY" \
    --namespace "$RELEASE_NAMESPACE" \
    --set-string "scenario=${PIPELINES_SCENARIO}" \
    --set crds.enabled=true \
    --set install.enabled=false \
    --wait \
    --timeout 5m

mapfile -t CUSTOM_RESOURCE_DEFINITION_NAMES < <(
    helm get manifest "$RELEASE_NAME" \
        --namespace "$RELEASE_NAMESPACE" |
        awk '
            $0 == "kind: CustomResourceDefinition" {
                custom_resource_definition = 1
                next
            }
            custom_resource_definition && /^  name: / {
                print $2
                custom_resource_definition = 0
            }
        '
)

if [[ "${#CUSTOM_RESOURCE_DEFINITION_NAMES[@]}" -eq 0 ]]; then
    echo "No CustomResourceDefinition resources were found in the Helm release." >&2
    exit 1
fi

for custom_resource_definition_name in "${CUSTOM_RESOURCE_DEFINITION_NAMES[@]}"; do
    kubectl wait \
        --for=condition=Established \
        "crd/${custom_resource_definition_name}" \
        --timeout=120s
done

helm upgrade "$RELEASE_NAME" "$CHART_DIRECTORY" \
    --namespace "$RELEASE_NAMESPACE" \
    --values "$SCENARIO_VALUES_FILE" \
    --wait \
    --timeout 20m

helm status "$RELEASE_NAME" --namespace "$RELEASE_NAMESPACE"

mapfile -t PIPELINES_DEPLOYMENT_NAMES < <(
    helm get manifest "$RELEASE_NAME" \
        --namespace "$RELEASE_NAMESPACE" |
        awk '
            $0 == "kind: Deployment" {
                deployment = 1
                next
            }
            deployment && /^  name: / {
                print $2
                deployment = 0
            }
        '
)

if [[ "${#PIPELINES_DEPLOYMENT_NAMES[@]}" -eq 0 ]]; then
    echo "No Deployment resources were found in the Helm release." >&2
    exit 1
fi

for deployment_name in "${PIPELINES_DEPLOYMENT_NAMES[@]}"; do
    kubectl rollout status \
        "deployment/${deployment_name}" \
        --namespace "$WORKLOAD_NAMESPACE" \
        --timeout=600s
done
