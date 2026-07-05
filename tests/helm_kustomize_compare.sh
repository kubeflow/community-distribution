#!/usr/bin/env bash
# Compare Helm vs Kustomize manifests for Kubeflow components

set -euo pipefail

COMPONENT=${1:-""}
SCENARIO=${2:-"base"}
SCRIPT_DIRECTORY="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIRECTORY="$(dirname "$SCRIPT_DIRECTORY")"

if [[ -z "$COMPONENT" ]]; then
    echo "ERROR: Component is required"
    echo "Usage: $0 <component> <scenario>"
    echo "Components: katib, hub, kserve-models-web-application, cert-manager"
    exit 1
fi

# Component-specific configurations
case "$COMPONENT" in
    "katib")
        CHART_DIRECTORY="$ROOT_DIRECTORY/experimental/helm/charts/katib"
        MANIFESTS_DIRECTORY="$ROOT_DIRECTORY/applications/katib/upstream"
        
        declare -A KUSTOMIZE_PATHS=(
            ["standalone"]="$MANIFESTS_DIRECTORY/installs/katib-standalone"
            ["cert-manager"]="$MANIFESTS_DIRECTORY/installs/katib-cert-manager"
            ["external-db"]="$MANIFESTS_DIRECTORY/installs/katib-external-db"
            ["leader-election"]="$MANIFESTS_DIRECTORY/installs/katib-leader-election"
            ["openshift"]="$MANIFESTS_DIRECTORY/installs/katib-openshift"
            ["standalone-postgres"]="$MANIFESTS_DIRECTORY/installs/katib-standalone-postgres"
            ["with-kubeflow"]="$MANIFESTS_DIRECTORY/installs/katib-with-kubeflow"
        )
        
        declare -A HELM_VALUES=(
            ["standalone"]="$CHART_DIRECTORY/ci/values-standalone.yaml"
            ["cert-manager"]="$CHART_DIRECTORY/ci/values-cert-manager.yaml"
            ["external-db"]="$CHART_DIRECTORY/ci/values-external-db.yaml"
            ["leader-election"]="$CHART_DIRECTORY/ci/values-leader-election.yaml"
            ["openshift"]="$CHART_DIRECTORY/ci/values-openshift.yaml"
            ["standalone-postgres"]="$CHART_DIRECTORY/ci/values-postgres.yaml"
            ["with-kubeflow"]="$CHART_DIRECTORY/ci/values-kubeflow.yaml"
            ["enterprise"]="$CHART_DIRECTORY/ci/values-enterprise.yaml"
            ["production"]="$CHART_DIRECTORY/ci/values-production.yaml"
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
        
    "hub")
        CHART_DIRECTORY="$ROOT_DIRECTORY/experimental/helm/charts/hub"
        MANIFESTS_DIRECTORY="$ROOT_DIRECTORY/applications/hub/upstream"
        
        declare -A KUSTOMIZE_PATHS=(
            ["base"]="$MANIFESTS_DIRECTORY/base"
            ["overlay-postgres"]="$MANIFESTS_DIRECTORY/overlays/postgres"
            ["overlay-db"]="$MANIFESTS_DIRECTORY/overlays/db"
            ["controller-manager"]="$MANIFESTS_DIRECTORY/options/controller/manager"
            ["controller-rbac"]="$MANIFESTS_DIRECTORY/options/controller/rbac"
            ["controller-default"]="$MANIFESTS_DIRECTORY/options/controller/default"
            ["controller-prometheus"]="$MANIFESTS_DIRECTORY/options/controller/prometheus"
            ["controller-network-policy"]="$MANIFESTS_DIRECTORY/options/controller/network-policy"
            ["ui-base"]="$MANIFESTS_DIRECTORY/options/ui/base"
            ["ui-standalone"]="$MANIFESTS_DIRECTORY/options/ui/overlays/standalone"
            ["ui-integrated"]="$MANIFESTS_DIRECTORY/options/ui/overlays/kubeflow"
            ["ui-istio"]="$MANIFESTS_DIRECTORY/options/ui/overlays/istio"
            ["istio"]="$MANIFESTS_DIRECTORY/options/istio"
            ["csi"]="$MANIFESTS_DIRECTORY/options/csi"
        )
        
        declare -A HELM_VALUES=(
            ["base"]="$CHART_DIRECTORY/ci/ci-values.yaml"
            ["overlay-postgres"]="$CHART_DIRECTORY/ci/values-postgres.yaml"
            ["overlay-db"]="$CHART_DIRECTORY/ci/values-db.yaml"
            ["controller-manager"]="$CHART_DIRECTORY/ci/values-controller-manager.yaml"
            ["controller-rbac"]="$CHART_DIRECTORY/ci/values-controller-rbac.yaml"
            ["controller-default"]="$CHART_DIRECTORY/ci/values-controller.yaml"
            ["controller-prometheus"]="$CHART_DIRECTORY/ci/values-controller-prometheus.yaml"
            ["controller-network-policy"]="$CHART_DIRECTORY/ci/values-controller-network-policy.yaml"
            ["ui-base"]="$CHART_DIRECTORY/ci/values-ui.yaml"
            ["ui-standalone"]="$CHART_DIRECTORY/ci/values-ui-standalone.yaml"
            ["ui-integrated"]="$CHART_DIRECTORY/ci/values-ui-integrated.yaml"
            ["ui-istio"]="$CHART_DIRECTORY/ci/values-ui-istio.yaml"
            ["istio"]="$CHART_DIRECTORY/ci/values-istio.yaml"
            ["csi"]="$CHART_DIRECTORY/ci/values-csi.yaml"
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
        
    "kserve-models-web-application")
        CHART_DIRECTORY="$ROOT_DIRECTORY/experimental/helm/charts/kserve-ui"
        MANIFESTS_DIRECTORY="$ROOT_DIRECTORY/applications/kserve/kserve-ui/upstream"
        
        declare -A KUSTOMIZE_PATHS=(
            ["base"]="$MANIFESTS_DIRECTORY/base"
            ["kubeflow"]="$MANIFESTS_DIRECTORY/overlays/kubeflow"
        )
        
        declare -A HELM_VALUES=(
            ["base"]="$CHART_DIRECTORY/ci/base-values.yaml"
            ["kubeflow"]="$CHART_DIRECTORY/ci/kubeflow-values.yaml"
        )
        
        declare -A NAMESPACES=(
            ["base"]="kserve"
            ["kubeflow"]="kubeflow"
        )
        ;;

    "cert-manager")
        CHART_DIRECTORY="$ROOT_DIRECTORY/common/cert-manager/helm"
        MANIFESTS_DIRECTORY="$ROOT_DIRECTORY/common/cert-manager"

        declare -A KUSTOMIZE_PATHS=(
            ["base"]="$MANIFESTS_DIRECTORY/base"
            ["kubeflow"]="$MANIFESTS_DIRECTORY/base"$'\n'"$MANIFESTS_DIRECTORY/overlays/kubeflow"
            ["existing-cert-manager"]="$MANIFESTS_DIRECTORY/overlays/kubeflow"
        )

        declare -A HELM_VALUES=(
            ["base"]="$CHART_DIRECTORY/ci/values-base.yaml"
            ["kubeflow"]="$CHART_DIRECTORY/ci/values-kubeflow.yaml"
            ["existing-cert-manager"]="$CHART_DIRECTORY/ci/values-existing-cert-manager.yaml"
        )

        declare -A NAMESPACES=(
            ["base"]="cert-manager"
            ["kubeflow"]="cert-manager"
            ["existing-cert-manager"]="cert-manager"
        )
        ;;

    *)
        echo "ERROR: Unknown component: $COMPONENT"
        echo "Supported components: katib, hub, kserve-models-web-application, cert-manager"
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
HELM_VALUES_ARGUMENTS="${HELM_VALUES[$SCENARIO]}"
NAMESPACE="${NAMESPACES[$SCENARIO]}"
mapfile -t KUSTOMIZE_ROOTS <<< "$KUSTOMIZE_PATH"

echo "Comparing $COMPONENT manifests for scenario: $SCENARIO"

for path in "${KUSTOMIZE_ROOTS[@]}"; do
    if [ ! -d "$path" ]; then
        echo "ERROR: Kustomize path does not exist: $path"
        exit 1
    fi
done

if [ ! -d "$CHART_DIRECTORY" ]; then
    echo "ERROR: Helm chart directory does not exist: $CHART_DIRECTORY"
    exit 1
fi

if [ -n "$HELM_VALUES_ARGUMENTS" ] && [ ! -f "$HELM_VALUES_ARGUMENTS" ]; then
    echo "ERROR: Helm values file does not exist: $HELM_VALUES_ARGUMENTS"
    exit 1
fi

KUSTOMIZE_OUTPUT="/tmp/kustomize-${COMPONENT}-${SCENARIO}.yaml"
HELM_OUTPUT="/tmp/helm-${COMPONENT}-${SCENARIO}.yaml"

cd "$ROOT_DIRECTORY"
: > "$KUSTOMIZE_OUTPUT"
for i in "${!KUSTOMIZE_ROOTS[@]}"; do
    path="${KUSTOMIZE_ROOTS[$i]}"
    if [ "$i" -gt 0 ]; then
        printf "\n---\n" >> "$KUSTOMIZE_OUTPUT"
    fi
    kustomize build "$path" >> "$KUSTOMIZE_OUTPUT"
done

# Generate Helm manifests (different approach for KServe UI)
cd "$ROOT_DIRECTORY"
if [[ "$COMPONENT" == "kserve-models-web-application" ]]; then
    # KServe uses chart-local CI values files, but still templates from the repository root.
    if [ -n "$HELM_VALUES_ARGUMENTS" ]; then
        helm template kserve-models-web-application "$CHART_DIRECTORY" \
            --namespace "$NAMESPACE" \
            --values "$HELM_VALUES_ARGUMENTS" > "$HELM_OUTPUT"
    else
        helm template kserve-models-web-application "$CHART_DIRECTORY" \
            --namespace "$NAMESPACE" > "$HELM_OUTPUT"
    fi
elif [[ "$COMPONENT" == "cert-manager" ]]; then
    cd "$CHART_DIRECTORY"
    if [[ "${CERT_MANAGER_DEPENDENCIES_READY:-false}" != "true" ]]; then
        helm repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || helm repo update jetstack >/dev/null
        helm dependency build .
    fi
    helm template cert-manager . \
        --namespace "$NAMESPACE" \
        --include-crds \
        --values "$HELM_VALUES_ARGUMENTS" > "$HELM_OUTPUT"
else
    cd "$CHART_DIRECTORY"
    if [[ "$COMPONENT" == "katib" ]]; then
        helm template katib . \
            --namespace "$NAMESPACE" \
            --include-crds \
            --values "$HELM_VALUES_ARGUMENTS" > "$HELM_OUTPUT"
    else
        helm template hub . \
            --namespace "$NAMESPACE" \
            --include-crds \
            --values "$HELM_VALUES_ARGUMENTS" > "$HELM_OUTPUT"
    fi
fi

cd "$ROOT_DIRECTORY"
python3 "$SCRIPT_DIRECTORY/helm_kustomize_compare.py" \
    "$KUSTOMIZE_OUTPUT" \
    "$HELM_OUTPUT" \
    "$COMPONENT" \
    "$SCENARIO" \
    "$NAMESPACE" \
    ${VERBOSE:+--verbose}

COMPARISON_RESULT=$?

rm -f "$KUSTOMIZE_OUTPUT" "$HELM_OUTPUT"



exit $COMPARISON_RESULT
