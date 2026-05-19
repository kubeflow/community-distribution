#!/bin/bash
set -euxo pipefail
kustomize build common/user-namespace/base | kubectl apply -f -
sleep 30 # Let the profile controler reconcile the namespace
PROFILE_CONTROLLER_POD=$(kubectl get pods -n kubeflow -o json | jq -r '.items[] | select(.metadata.name | startswith("profiles-deployment")) | .metadata.name')
kubectl logs -n kubeflow "$PROFILE_CONTROLLER_POD"
KF_PROFILE=kubeflow-user-example-com
kubectl -n $KF_PROFILE get pods,configmaps,secrets
echo "Waiting for PSS restricted label to persist..."
for i in $(seq 1 10); do
  LABEL=$(kubectl get ns $KF_PROFILE \
    -o jsonpath='{.metadata.labels.pod-security\.kubernetes\.io/enforce}')
  [ "$LABEL" = "restricted" ] && break
  echo "Label not yet stable (got: $LABEL), retrying..."
  kubectl label ns $KF_PROFILE \
    pod-security.kubernetes.io/enforce=restricted \
    pod-security.kubernetes.io/enforce-version=v1.29 \
    --overwrite
  sleep 5
done
[ "$LABEL" != "restricted" ] && echo "ERROR: Could not set restricted label" && exit 1
