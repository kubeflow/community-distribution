#!/usr/bin/env bash
# Eventing core only: no broker or channel provider is added here.
set -euo pipefail
chart=common/knative/knative-eventing/helm
kubectl get namespace kubeflow >/dev/null
phase=definitions
if helm status knative-eventing --namespace kubeflow >/dev/null 2>&1; then
    phase=$(helm get values knative-eventing --namespace kubeflow -o json | \
        python3 -c 'import json,sys; print((json.load(sys.stdin) or {}).get("installation", {}).get("phase", "complete"))')
else
    helm install knative-eventing "$chart" --namespace kubeflow \
        --set installation.phase=definitions --wait --timeout 5m
fi
case "$phase" in
    definitions)
        kubectl wait --for=condition=Established --timeout=120s \
            -f "$chart/manifests/platform-crds.yaml"
        ;;
    complete) ;;
    *) echo "Unknown saved bootstrap phase: $phase" >&2; exit 1 ;;
esac
helm upgrade knative-eventing "$chart" --namespace kubeflow --reset-values \
    --set installation.phase=complete --wait --timeout 10m
for deployment in eventing-controller eventing-webhook job-sink pingsource-mt-adapter; do
    kubectl rollout status "deployment/$deployment" -n knative-eventing --timeout=120s
done
kubectl get deployment/pingsource-mt-adapter -n knative-eventing -o json | \
    python3 -c 'import json,sys
adapter=json.load(sys.stdin)
assert adapter["spec"].get("replicas",0) >= 1, "Expected an idle adapter before creating PingSources"
assert adapter.get("status",{}).get("availableReplicas",0) >= 1, "Idle adapter is not healthy"'
kubectl rollout status statefulset/request-reply -n knative-eventing --timeout=120s
