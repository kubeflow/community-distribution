#!/bin/bash
set -euxo pipefail
kustomize build common/user-namespace/base | kubectl apply -f -
sleep 30 # Let the profile controler reconcile the namespace
PROFILE_CONTROLLER_POD=$(kubectl get pods -n kubeflow -o json | jq -r '.items[] | select(.metadata.name | startswith("profiles-deployment")) | .metadata.name')
kubectl logs -n kubeflow "$PROFILE_CONTROLLER_POD"
KF_PROFILE=kubeflow-user-example-com
kubectl -n "$KF_PROFILE" get pods,configmaps,secrets

PSS_ENFORCE=baseline
if [[ "${GITHUB_ACTIONS:-false}" == "true" ]]; then
  PSS_ENFORCE=restricted
fi

kubectl label namespace "$KF_PROFILE" \
  "pod-security.kubernetes.io/enforce=${PSS_ENFORCE}" \
  --overwrite

if [[ "$PSS_ENFORCE" == "restricted" ]]; then
  kubectl label namespace "$KF_PROFILE" \
    pod-security.kubernetes.io/enforce-version=latest \
    --overwrite
fi

kubectl get namespace "$KF_PROFILE" \
  -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}' | grep -qx "$PSS_ENFORCE"

if [[ "$PSS_ENFORCE" == "restricted" ]]; then
  kubectl get namespace "$KF_PROFILE" \
    -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce-version}' | grep -qx latest
fi
