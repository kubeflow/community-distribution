#!/usr/bin/env bash
# Compare Helm vs Kustomize manifests for all scenarios of Kubeflow components

set -euo pipefail

COMPONENT=${1:-"all"}
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Define all scenarios for each component
declare -A COMPONENT_SCENARIOS=(
    ["katib"]="standalone cert-manager external-db leader-election openshift standalone-postgres with-kubeflow"
    ["hub"]="base overlay-postgres overlay-db controller-manager controller-rbac controller-default controller-prometheus controller-network-policy ui-base ui-standalone ui-integrated ui-istio istio csi"
    ["kserve-models-web-app"]="base kubeflow"
    ["istio"]="crds base oauth2-proxy cluster-local-gateway kubeflow-istio-resources platform-full"
)

test_component() {
    local component=$1
    local scenarios_str="${COMPONENT_SCENARIOS[$component]}"
    
    if [[ -z "$scenarios_str" ]]; then
        echo "ERROR: Unknown component: $component"
        return 1
    fi
    
    local scenarios=($scenarios_str)
    
    declare -a passed_scenarios=()
    declare -a failed_scenarios=()
    
    for scenario in "${scenarios[@]}"; do
        if "$SCRIPT_DIR/helm_kustomize_compare.sh" "$component" "$scenario"; then
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
    
    for comp in katib hub kserve-models-web-app istio; do
        if test_component "$comp"; then
            passed_components+=("$comp")
        else
            echo "FAILED: $comp"
            failed_components+=("$comp")
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
    echo "  kserve-models-web-app  Test KServe Models Web App scenarios"
    echo "  istio                  Test Istio wrapper scenarios"
    echo ""
    echo "Examples:"
    echo "  $0                     # Test all components"
    echo "  $0 katib               # Test only Katib"
    echo "  $0 hub                 # Test only Hub / Model Registry"
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
    echo "Supported components: katib, hub, kserve-models-web-app, istio, all"
    echo "Use '$0 help' for more information."
    exit 1
fi 
