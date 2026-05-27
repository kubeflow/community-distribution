#!/bin/bash
set -euxo pipefail

KF_PROFILE=${1:-kubeflow-user-example-com}
KATIB_SUGGESTION_DEPLOYMENT=grid-grid

dump_katib_debug() {
  kubectl get experiments.kubeflow.org -n "$KF_PROFILE" -o yaml || true
  kubectl get trials.kubeflow.org -n "$KF_PROFILE" -o yaml || true
  kubectl get deployments,replicasets,jobs,pods -n "$KF_PROFILE" -o wide --show-labels || true
  kubectl describe experiments.kubeflow.org -n "$KF_PROFILE" || true
  kubectl describe trials.kubeflow.org -n "$KF_PROFILE" || true
  kubectl describe deployments,replicasets,jobs,pods -n "$KF_PROFILE" || true
  kubectl get events -n "$KF_PROFILE" --sort-by=.metadata.creationTimestamp || true
  kubectl logs -n kubeflow deployment/katib-controller --tail=100 || true
}

wait_for_katib_suggestion_deployment() {
  for _ in $(seq 1 90); do
    if kubectl get deployment "$KATIB_SUGGESTION_DEPLOYMENT" -n "$KF_PROFILE" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done

  return 1
}

patch_katib_suggestion_deployment() {
  wait_for_katib_suggestion_deployment || return 1
  kubectl patch deployment "$KATIB_SUGGESTION_DEPLOYMENT" -n "$KF_PROFILE" --type=json -p='[
    {
      "op": "add",
      "path": "/spec/template/spec/containers/0/securityContext",
      "value": {
        "allowPrivilegeEscalation": false,
        "capabilities": {
          "drop": ["ALL"]
        },
        "runAsNonRoot": true,
        "runAsUser": 1000,
        "seccompProfile": {
          "type": "RuntimeDefault"
        }
      }
    }
  ]' || return 1
  kubectl rollout status deployment/"$KATIB_SUGGESTION_DEPLOYMENT" -n "$KF_PROFILE" --timeout=180s
}

kubectl apply -f tests/katib_test.yaml
patch_katib_suggestion_deployment || (
  dump_katib_debug
  exit 1
)
kubectl wait --for=condition=Running experiments.kubeflow.org -n "$KF_PROFILE" --all --timeout=180s || (
  dump_katib_debug
  exit 1
)
echo "Waiting for all Trials to be Completed..."
kubectl wait --for=condition=Created trials.kubeflow.org -n "$KF_PROFILE" --all --timeout=180s || (
  dump_katib_debug
  exit 1
)
kubectl get trials.kubeflow.org -n "$KF_PROFILE"
kubectl wait --for=condition=Succeeded trials.kubeflow.org -n "$KF_PROFILE" --all --timeout 600s || (
  dump_katib_debug
  exit 1
)
kubectl get trials.kubeflow.org -n "$KF_PROFILE"
