#!/usr/bin/env bash
# Compare Helm vs Kustomize manifests for all scenarios of Kubeflow components

set -euo pipefail

COMPONENT=${1:-"all"}
SCRIPT_DIRECTORY="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIRECTORY="$(dirname "$SCRIPT_DIRECTORY")"

# Define all scenarios for each component
declare -A COMPONENT_SCENARIOS=(
    ["katib"]="standalone cert-manager external-db leader-election openshift standalone-postgres with-kubeflow"
    ["hub"]="base overlay-postgres overlay-db controller-manager controller-rbac controller-default controller-prometheus controller-network-policy ui-base ui-standalone ui-integrated ui-istio istio csi"
    ["kserve-models-web-application"]="kubeflow"
    ["cert-manager"]="base kubeflow existing-cert-manager"
    ["kubeflow-namespaces"]="base platform-namespaces"
    ["kubeflow-platform"]="base"
    ["dex"]="oauth2-proxy"
    ["oauth2-proxy"]="m2m-dex-and-kind"
    ["istio"]="crds base oauth2-proxy gke cluster-local-gateway kubeflow-istio-resources platform-full"
    ["kubeflow-dashboard"]="platform"
    ["kubeflow-notebooks"]="platform"
)

prepare_component() {
    local component=$1

    if [[ "$component" == "cert-manager" ]]; then
        helm repo add jetstack https://charts.jetstack.io >/dev/null 2>&1 || helm repo update jetstack >/dev/null
        helm dependency build "$ROOT_DIRECTORY/common/cert-manager/helm" >/dev/null
    fi
}

test_component() {
    local component=$1
    local scenario_names="${COMPONENT_SCENARIOS[$component]}"

    if [[ -z "$scenario_names" ]]; then
        echo "ERROR: Unknown component: $component"
        return 1
    fi

    local scenarios=()
    read -r -a scenarios <<< "$scenario_names"

    declare -a passed_scenarios=()
    declare -a failed_scenarios=()

    prepare_component "$component"

    for scenario in "${scenarios[@]}"; do
        if CERT_MANAGER_DEPENDENCIES_READY=true "$SCRIPT_DIRECTORY/helm_kustomize_compare.sh" "$component" "$scenario"; then
            passed_scenarios+=("$scenario")
        else
            echo "FAILED: $component/$scenario"
            failed_scenarios+=("$scenario")
        fi
    done

    if [ ${#failed_scenarios[@]} -gt 0 ]; then
        return 1
    fi

    return 0
}

if [[ "$COMPONENT" == "all" ]]; then

    declare -a passed_components=()
    declare -a failed_components=()

    for component in katib hub kserve-models-web-application cert-manager kubeflow-namespaces kubeflow-platform dex oauth2-proxy istio kubeflow-dashboard kubeflow-notebooks; do
        if test_component "$component"; then
            passed_components+=("$component")
        else
            echo "FAILED: $component"
            failed_components+=("$component")
        fi
    done

    if [ ${#failed_components[@]} -gt 0 ]; then
        echo "FAILED: Some components have differences between Helm and Kustomize manifests."
        exit 1
    else
        echo "SUCCESS: All components passed! Helm and Kustomize manifests are equivalent."
        exit 0
    fi

elif [[ "$COMPONENT" == "help" ]] || [[ "$COMPONENT" == "--help" ]] || [[ "$COMPONENT" == "-h" ]]; then
    echo "Usage: $0 [component]"
    echo ""
    echo "Arguments:"
    echo "  component    Component to test (default: all)"
    echo ""
    echo "Components:"
    echo "  all                    Test all components"
    echo "  katib                  Test Katib scenarios"
    echo "  hub                    Test Hub / Model Registry scenarios"
    echo "  kserve-models-web-application  Test KServe UI scenarios"
    echo "  cert-manager           Test cert-manager wrapper scenarios"
    echo "  kubeflow-namespaces    Test Kubeflow namespace foundation chart"
    echo "  kubeflow-platform      Test Kubeflow platform foundation chart"
    echo "  dex                    Test Dex scenarios"
    echo "  oauth2-proxy           Test oauth2-proxy wrapper scenarios"
    echo "  istio                  Test Istio wrapper scenarios"
    echo "  kubeflow-dashboard     Test Kubeflow Dashboard platform scenario"
    echo "  kubeflow-notebooks     Test Kubeflow Notebooks platform scenario"
    echo ""
    echo "Examples:"
    echo "  $0                     # Test all components"
    echo "  $0 katib               # Test only Katib"
    echo "  $0 hub                 # Test only Hub / Model Registry"
    echo "  $0 dex                 # Test only Dex"
    echo "  $0 kubeflow-dashboard  # Test only Kubeflow Dashboard platform"
    exit 0

elif [[ "${COMPONENT_SCENARIOS[$COMPONENT]:-}" ]]; then
    # Test specific component
    if test_component "$COMPONENT"; then
        echo "SUCCESS: All scenarios passed for $COMPONENT!"
        exit 0
    else
        echo "FAILED: Some scenarios failed for $COMPONENT."
        exit 1
    fi

else
    echo "ERROR: Unknown component: $COMPONENT"
    echo "Supported components: katib, hub, kserve-models-web-application, cert-manager, kubeflow-namespaces, kubeflow-platform, dex, oauth2-proxy, istio, kubeflow-dashboard, kubeflow-notebooks, all"
    echo "Use '$0 help' for more information."
    exit 1
fi
