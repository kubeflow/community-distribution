#!/bin/bash
set -euxo pipefail

echo "Installing Profiles Controller with PSS (Pod Security Standards)"
kustomize build applications/dashboard/upstream/profile-controller/overlays/kubeflow-pss | kubectl apply -f -
kubectl -n kubeflow rollout status deployment/profiles-deployment --timeout=180s
kubectl -n kubeflow wait --for=condition=Ready pods -l app=profile-controller --timeout=180s
kubectl wait --for=condition=Established --timeout=60s crd/profiles.kubeflow.org

# Patch Profiles namespace labels config to enforce restricted instead of baseline in CI.
# We use standard json patching to dynamically rewrite the embedded namespace-labels.yaml file
# inside the ConfigMap.
# Since Kustomize appends a dynamic hash suffix to the ConfigMap name, we query the exact name first.
CONFIGMAP_NAME=$(kubectl -n kubeflow get configmaps -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n' | grep '^profiles-namespace-labels-data-' | head -n 1)
if [ -z "$CONFIGMAP_NAME" ]; then
    echo "ERROR: Could not find configmap profiles-namespace-labels-data with hash suffix"
    exit 1
fi

kubectl patch configmap "$CONFIGMAP_NAME" -n kubeflow --type=json \
  -p='[{"op": "replace", "path": "/data/namespace-labels.yaml", "value": "app.kubernetes.io/part-of: \"kubeflow-profile\"\nkatib.kubeflow.org/metrics-collector-injection: \"enabled\"\npipelines.kubeflow.org/enabled: \"true\"\nserving.kubeflow.org/inferenceservice: \"enabled\"\npod-security.kubernetes.io/enforce: \"restricted\"\npod-security.kubernetes.io/enforce-version: \"v1.29\"\n"}]'

# Restart profiles deployment to pick up the updated ConfigMap immediately
kubectl rollout restart deployment/profiles-deployment -n kubeflow
kubectl rollout status deployment/profiles-deployment -n kubeflow --timeout=120s


