#!/bin/bash
set -euxo

REPOSITORY_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "${GITHUB_WORKSPACE:-$(pwd)}")
cd "${REPOSITORY_ROOT}"

# Install Spark operator
kustomize build applications/spark/spark-operator/overlays/kubeflow | kubectl -n kubeflow apply --server-side --force-conflicts -f -

# Wait for the operator controller to be ready.
kubectl -n kubeflow wait --for=condition=available --timeout=180s deploy/spark-operator-controller
kubectl -n kubeflow get pod -l app.kubernetes.io/name=spark-operator

# Wait for the operator webhook to be ready.
kubectl -n kubeflow wait --for=condition=available --timeout=180s deploy/spark-operator-webhook
kubectl -n kubeflow wait \
  --for=condition=Ready \
  pod \
  -l app.kubernetes.io/name=spark-operator,app.kubernetes.io/component=webhook \
  --timeout=180s
# Wait for the webhook endpoint to be registered and routable
kubectl -n kubeflow wait \
  --for=jsonpath='{.subsets[0].addresses[0].targetRef.kind}'=Pod \
  endpoints/spark-operator-webhook-svc \
  --timeout=180s
sleep 10 # some readinessprobes for the webhook are not valid
kubectl -n kubeflow get pod -l app.kubernetes.io/name=spark-operator
