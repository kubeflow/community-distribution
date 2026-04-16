#!/usr/bin/env bash
# Compare Helm vs Kustomize manifests for Kubeflow components

set -euo pipefail

COMPONENT=${1:-""}
SCENARIO=${2:-"base"}
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

if [[ -z "$COMPONENT" ]]; then
    echo "ERROR: Component is required"
    echo "Usage: $0 <component> <scenario>"
    echo "Components: katib, model-registry, kserve-models-web-app"
    exit 1
fi

# Component-specific configurations
case "$COMPONENT" in
    "katib")
        CHART_DIR="$ROOT_DIR/experimental/helm/charts/katib"
        MANIFESTS_DIR="$ROOT_DIR/applications/katib/upstream"
        
        declare -A KUSTOMIZE_PATHS=(
            ["standalone"]="$MANIFESTS_DIR/installs/katib-standalone"
            ["cert-manager"]="$MANIFESTS_DIR/installs/katib-cert-manager"
            ["external-db"]="$MANIFESTS_DIR/installs/katib-external-db"
            ["leader-election"]="$MANIFESTS_DIR/installs/katib-leader-election"
            ["openshift"]="$MANIFESTS_DIR/installs/katib-openshift"
            ["standalone-postgres"]="$MANIFESTS_DIR/installs/katib-standalone-postgres"
            ["with-kubeflow"]="$MANIFESTS_DIR/installs/katib-with-kubeflow"
        )
        
        declare -A HELM_VALUES=(
            ["standalone"]="$CHART_DIR/ci/values-standalone.yaml"
            ["cert-manager"]="$CHART_DIR/ci/values-cert-manager.yaml"
            ["external-db"]="$CHART_DIR/ci/values-external-db.yaml"
            ["leader-election"]="$CHART_DIR/ci/values-leader-election.yaml"
            ["openshift"]="$CHART_DIR/ci/values-openshift.yaml"
            ["standalone-postgres"]="$CHART_DIR/ci/values-postgres.yaml"
            ["with-kubeflow"]="$CHART_DIR/ci/values-kubeflow.yaml"
            ["enterprise"]="$CHART_DIR/ci/values-enterprise.yaml"
            ["production"]="$CHART_DIR/ci/values-production.yaml"
        )
        
        declare -A NAMESPACES=(
            ["standalone"]="kubeflow"
            ["cert-manager"]="kubeflow"
            ["external-db"]="kubeflow"
            ["leader-election"]="kubeflow"
            ["openshift"]="kubeflow"
            ["standalone-postgres"]="kubeflow"
            ["with-kubeflow"]="kubeflow"
            ["enterprise"]="kubeflow"
            ["production"]="kubeflow"
        )
        ;;
        
    "model-registry")
        CHART_DIR="$ROOT_DIR/experimental/helm/charts/model-registry"
        MANIFESTS_DIR="$ROOT_DIR/applications/model-registry/upstream"
        
        declare -A KUSTOMIZE_PATHS=(
            ["base"]="$MANIFESTS_DIR/base"
            ["overlay-postgres"]="$MANIFESTS_DIR/overlays/postgres"
            ["overlay-db"]="$MANIFESTS_DIR/overlays/db"
            ["controller-manager"]="$MANIFESTS_DIR/options/controller/manager"
            ["controller-rbac"]="$MANIFESTS_DIR/options/controller/rbac" 
            ["controller-default"]="$MANIFESTS_DIR/options/controller/default"
            ["controller-prometheus"]="$MANIFESTS_DIR/options/controller/prometheus"
            ["controller-network-policy"]="$MANIFESTS_DIR/options/controller/network-policy"
            ["ui-base"]="$MANIFESTS_DIR/options/ui/base"
            ["ui-standalone"]="$MANIFESTS_DIR/options/ui/overlays/standalone"
            ["ui-integrated"]="$MANIFESTS_DIR/options/ui/overlays/kubeflow"
            ["ui-istio"]="$MANIFESTS_DIR/options/ui/overlays/istio"
            ["istio"]="$MANIFESTS_DIR/options/istio"
            ["csi"]="$MANIFESTS_DIR/options/csi"
        )
        
        declare -A HELM_VALUES=(
            ["base"]="$CHART_DIR/ci/ci-values.yaml"
            ["overlay-postgres"]="$CHART_DIR/ci/values-postgres.yaml"
            ["overlay-db"]="$CHART_DIR/ci/values-db.yaml"
            ["controller-manager"]="$CHART_DIR/ci/values-controller-manager.yaml"
            ["controller-rbac"]="$CHART_DIR/ci/values-controller-rbac.yaml"
            ["controller-default"]="$CHART_DIR/ci/values-controller.yaml"
            ["controller-prometheus"]="$CHART_DIR/ci/values-controller-prometheus.yaml"
            ["controller-network-policy"]="$CHART_DIR/ci/values-controller-network-policy.yaml"
            ["ui-base"]="$CHART_DIR/ci/values-ui.yaml"
            ["ui-standalone"]="$CHART_DIR/ci/values-ui-standalone.yaml"
            ["ui-integrated"]="$CHART_DIR/ci/values-ui-integrated.yaml"
            ["ui-istio"]="$CHART_DIR/ci/values-ui-istio.yaml"
            ["istio"]="$CHART_DIR/ci/values-istio.yaml"
            ["csi"]="$CHART_DIR/ci/values-csi.yaml"
        )
        
        declare -A NAMESPACES=(
            ["base"]="kubeflow"
            ["overlay-postgres"]="kubeflow"
            ["overlay-db"]="kubeflow"
            ["controller-manager"]="kubeflow"
            ["controller-rbac"]="kubeflow"
            ["controller-default"]="kubeflow"
            ["controller-prometheus"]="kubeflow"
            ["controller-network-policy"]="kubeflow"
            ["ui-base"]="kubeflow"
            ["ui-standalone"]="kubeflow"
            ["ui-integrated"]="kubeflow"
            ["ui-istio"]="kubeflow"
            ["istio"]="kubeflow"
            ["csi"]="kubeflow"
        )
        ;;
        
    "kserve-models-web-app")
        CHART_DIR="$ROOT_DIR/experimental/helm/charts/kserve-models-web-app"
        MANIFESTS_DIR="$ROOT_DIR/applications/kserve/models-web-app"
        
        declare -A KUSTOMIZE_PATHS=(
            ["base"]="$MANIFESTS_DIR/base"
            ["kubeflow"]="$MANIFESTS_DIR/overlays/kubeflow"
        )
        
        declare -A HELM_VALUES=(
            ["base"]="$CHART_DIR/ci/base-values.yaml"
            ["kubeflow"]="$CHART_DIR/ci/kubeflow-values.yaml"
        )
        
        declare -A NAMESPACES=(
            ["base"]="kserve"
            ["kubeflow"]="kubeflow"
        )
        ;;

    *)
        echo "ERROR: Unknown component: $COMPONENT"
        echo "Supported components: katib, model-registry, kserve-models-web-app"
        exit 1
        ;;
esac

if [[ ! "${KUSTOMIZE_PATHS[$SCENARIO]:-}" ]]; then
    echo "ERROR: Unknown scenario '$SCENARIO' for component '$COMPONENT'"
    echo "Supported scenarios for $COMPONENT:"
    for scenario in "${!KUSTOMIZE_PATHS[@]}"; do
        echo "  - $scenario"
    done
    exit 1
fi

KUSTOMIZE_PATH="${KUSTOMIZE_PATHS[$SCENARIO]}"
HELM_VALUES_ARG="${HELM_VALUES[$SCENARIO]}"
NAMESPACE="${NAMESPACES[$SCENARIO]}"

echo "Comparing $COMPONENT manifests for scenario: $SCENARIO"

if [ ! -d "$KUSTOMIZE_PATH" ]; then
    echo "ERROR: Kustomize path does not exist: $KUSTOMIZE_PATH"
    exit 1
fi

if [ ! -d "$CHART_DIR" ]; then
    echo "ERROR: Helm chart directory does not exist: $CHART_DIR"
    exit 1
fi

if [ -n "$HELM_VALUES_ARG" ] && [ ! -f "$HELM_VALUES_ARG" ]; then
    echo "ERROR: Helm values file does not exist: $HELM_VALUES_ARG"
    exit 1
fi

KUSTOMIZE_OUTPUT="/tmp/kustomize-${COMPONENT}-${SCENARIO}.yaml"
HELM_OUTPUT="/tmp/helm-${COMPONENT}-${SCENARIO}.yaml"

cd "$ROOT_DIR"
kustomize build "$KUSTOMIZE_PATH" > "$KUSTOMIZE_OUTPUT"

# Generate Helm manifests (different approach for KServe Models Web App)
cd "$ROOT_DIR"
if [[ "$COMPONENT" == "kserve-models-web-app" ]]; then
    # KServe uses chart-local CI values files, but still templates from the repository root.
    if [ -n "$HELM_VALUES_ARG" ]; then
        helm template kserve-models-web-application "$CHART_DIR" \
            --namespace "$NAMESPACE" \
            --values "$HELM_VALUES_ARG" > "$HELM_OUTPUT"
    else
        helm template kserve-models-web-application "$CHART_DIR" \
            --namespace "$NAMESPACE" > "$HELM_OUTPUT"
    fi
else
    cd "$CHART_DIR"
    if [[ "$COMPONENT" == "katib" ]]; then
        helm template katib . \
            --namespace "$NAMESPACE" \
            --include-crds \
            --values "$HELM_VALUES_ARG" > "$HELM_OUTPUT"
    else
        helm template model-registry . \
            --namespace "$NAMESPACE" \
            --include-crds \
            --values "$HELM_VALUES_ARG" > "$HELM_OUTPUT"
    fi
fi

cd "$ROOT_DIR"
python3 "$SCRIPT_DIR/helm_kustomize_compare.py" \
    "$KUSTOMIZE_OUTPUT" \
    "$HELM_OUTPUT" \
    "$COMPONENT" \
    "$SCENARIO" \
    "$NAMESPACE" \
    ${VERBOSE:+--verbose}

COMPARISON_RESULT=$?

rm -f "$KUSTOMIZE_OUTPUT" "$HELM_OUTPUT"



exit $COMPARISON_RESULT
