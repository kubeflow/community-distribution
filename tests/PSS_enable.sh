#!/bin/bash
set -euo pipefail

PSS_LEVEL="${1:-restricted}"

[[ "$PSS_LEVEL" == "baseline" || "$PSS_LEVEL" == "restricted" ]] || {
    echo "ERROR: Invalid PSS level '$PSS_LEVEL'. Usage: $0 [baseline|restricted]"
    exit 1
}

NAMESPACES=("istio-system" "auth" "cert-manager" "oauth2-proxy" "kubeflow" "knative-serving" "kubeflow-system" "kubeflow-workspaces")
[[ "$PSS_LEVEL" == "baseline" ]] && NAMESPACES+=("kubeflow-user-example-com")

echo "Applying PSS $PSS_LEVEL to: ${NAMESPACES[*]}"

for NAMESPACE in "${NAMESPACES[@]}"; do
    if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
        continue
    fi

    PATCH_OUTPUT=$(kubectl label namespace "$NAMESPACE" "pod-security.kubernetes.io/enforce=$PSS_LEVEL" --overwrite 2>&1)
    if echo "$PATCH_OUTPUT" | grep -q "violate the new PodSecurity"; then
        echo "ERROR: PSS violation in namespace $NAMESPACE"
        echo "$PATCH_OUTPUT" | grep -A 5 "violate the new PodSecurity"
        exit 1
    fi
    echo "✅ $NAMESPACE"
done
