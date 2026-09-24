#!/usr/bin/env bash
# Helm counterpart of tests/spark_install.sh, proven equivalent to
# applications/spark/spark-operator/overlays/kubeflow by the spark-operator
# comparison scenario.
set -euxo pipefail

REPOSITORY_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "${GITHUB_WORKSPACE:-$(pwd)}")
cd "${REPOSITORY_ROOT}"

CHART_DIRECTORY="applications/spark/spark-operator/helm"
CHART_REPOSITORY="https://kubeflow.github.io/spark-operator"

# The upstream chart is a dependency that is never committed. Build it in a
# temporary copy with an isolated Helm environment, so that no archive is left
# in the source tree and the caller's Helm repositories are not changed.
WORK_DIRECTORY="$(mktemp -d)"
cleanup() {
  rm -rf "${WORK_DIRECTORY}"
}
trap cleanup EXIT
CHART_COPY="${WORK_DIRECTORY}/spark-operator"
cp -R "${CHART_DIRECTORY}" "${CHART_COPY}"
(
  # shellcheck source=scripts/library.sh
  source "${REPOSITORY_ROOT}/scripts/library.sh"
  isolate_helm_environment "${WORK_DIRECTORY}/helm"
  helm repo add spark-operator "${CHART_REPOSITORY}"
  helm dependency build "${CHART_COPY}"
)

echo "Installing Spark Operator with Helm ..."
helm install spark-operator "${CHART_COPY}" \
  --namespace kubeflow \
  --values "${CHART_COPY}/ci/values-kubeflow.yaml" \
  --wait --timeout 5m

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
# Wait for the webhook certificate authority. The webhook pod is ready before it
# writes caBundle: it writes it only as the leader, and after a reinstallation
# it first waits for the Lease of the previous pod to expire. Until then the
# API server rejects every SparkApplication with "x509: certificate signed by
# unknown authority".
kubectl wait --timeout=180s --for='jsonpath={.webhooks[0].clientConfig.caBundle}' \
  mutatingwebhookconfiguration/spark-operator-webhook \
  validatingwebhookconfiguration/spark-operator-webhook
sleep 10 # some readiness probes for the webhook are not valid
kubectl -n kubeflow get pod -l app.kubernetes.io/name=spark-operator
