#!/usr/bin/env bash
# Lifecycle evidence for the Spark Operator Helm chart. It is run by hand on a
# cluster where tests/spark_helm_install.sh has installed the release and a
# Profile namespace exists; it is not part of any workflow.
#
# It proves what `helm uninstall` and a later `helm install` do:
#   - the three custom resource definitions and a user SparkApplication with
#     the same UID remain after the uninstallation;
#   - every object of the release, including the operator workloads, the
#     webhook configurations, the service accounts and the three aggregated
#     ClusterRoles, is deleted;
#   - after the reinstallation the operator reconciles again: a new
#     SparkApplication completes, and a specification change to the retained
#     one is submitted again and completes.
# It makes no claim that a running application continues without the operator.
set -euxo pipefail

NAMESPACE=$1
REPOSITORY_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "${GITHUB_WORKSPACE:-$(pwd)}")
cd "${REPOSITORY_ROOT}"

SPARK_APPLICATION_YAML="applications/spark/sparkapplication_example.yaml"
RETAINED_APPLICATION="spark-pi-python"
NEW_APPLICATION="reinstallation-spark-pi"
CUSTOM_RESOURCE_DEFINITIONS=(
  scheduledsparkapplications.sparkoperator.k8s.io
  sparkapplications.sparkoperator.k8s.io
  sparkconnects.sparkoperator.k8s.io
)
AGGREGATED_ROLES=(kubeflow-spark-admin kubeflow-spark-edit kubeflow-spark-view)
OPERATOR_DEPLOYMENTS=(spark-operator-controller spark-operator-webhook)

wait_for_application_state() {
  local application="$1"
  local expected="$2"
  local state=""
  for _ in $(seq 1 120); do
    state=$(kubectl -n "${NAMESPACE}" get sparkapplication "${application}" \
      -o jsonpath='{.status.applicationState.state}')
    if [[ "${state}" == "${expected}" ]]; then
      return 0
    fi
    if [[ "${state}" == "FAILED" ]]; then
      break
    fi
    sleep 5
  done
  echo "ERROR: SparkApplication ${application} is ${state:-without a state}, expected ${expected}." >&2
  kubectl -n "${NAMESPACE}" describe sparkapplication "${application}" >&2
  return 1
}

# The controller gives every submission a new status.submissionID.
wait_for_new_submission() {
  local application="$1"
  local previous="$2"
  local current=""
  for _ in $(seq 1 60); do
    current=$(kubectl -n "${NAMESPACE}" get sparkapplication "${application}" \
      -o jsonpath='{.status.submissionID}')
    if [[ -n "${current}" && "${current}" != "${previous}" ]]; then
      return 0
    fi
    sleep 5
  done
  echo "ERROR: SparkApplication ${application} was not submitted again, status.submissionID is still ${current}." >&2
  kubectl -n "${NAMESPACE}" describe sparkapplication "${application}" >&2
  return 1
}

definition_identifiers() {
  kubectl get customresourcedefinitions "${CUSTOM_RESOURCE_DEFINITIONS[@]}" \
    -o jsonpath='{range .items[*]}{.metadata.name}={.metadata.uid}{"\n"}{end}'
}

RELEASE_MANIFEST="$(mktemp)"
cleanup() {
  rm -f "${RELEASE_MANIFEST}"
  kubectl -n "${NAMESPACE}" delete sparkapplication \
    "${RETAINED_APPLICATION}" "${NEW_APPLICATION}" --ignore-not-found
}
trap cleanup EXIT

kubectl label namespace "${NAMESPACE}" istio-injection=enabled --overwrite

# 1. A user SparkApplication that the operator has reconciled to completion.
kubectl -n "${NAMESPACE}" apply -f "${SPARK_APPLICATION_YAML}"
wait_for_application_state "${RETAINED_APPLICATION}" COMPLETED
APPLICATION_IDENTIFIER_BEFORE=$(kubectl -n "${NAMESPACE}" get sparkapplication \
  "${RETAINED_APPLICATION}" -o jsonpath='{.metadata.uid}')
SUBMISSION_IDENTIFIER_BEFORE=$(kubectl -n "${NAMESPACE}" get sparkapplication \
  "${RETAINED_APPLICATION}" -o jsonpath='{.status.submissionID}')
DEFINITION_IDENTIFIERS_BEFORE=$(definition_identifiers)
helm get manifest spark-operator --namespace kubeflow > "${RELEASE_MANIFEST}"

# 2. Uninstall the release.
helm uninstall spark-operator --namespace kubeflow --wait --timeout 5m

# 3. The definitions and the user object remain with the same identity.
[[ "$(definition_identifiers)" == "${DEFINITION_IDENTIFIERS_BEFORE}" ]]
APPLICATION_IDENTIFIER_AFTER=$(kubectl -n "${NAMESPACE}" get sparkapplication \
  "${RETAINED_APPLICATION}" -o jsonpath='{.metadata.uid}')
[[ "${APPLICATION_IDENTIFIER_AFTER}" == "${APPLICATION_IDENTIFIER_BEFORE}" ]]

# 4. Every object of the release is deleted, among them the operator workloads
# and the aggregated roles. The definitions are not part of the release manifest.
[[ -z "$(kubectl -n kubeflow get -f "${RELEASE_MANIFEST}" --ignore-not-found -o name)" ]]
for deployment in "${OPERATOR_DEPLOYMENTS[@]}"; do
  [[ -z "$(kubectl -n kubeflow get deployment "${deployment}" --ignore-not-found -o name)" ]]
done
kubectl -n kubeflow wait --for=delete pod -l app.kubernetes.io/name=spark-operator --timeout=180s
for role in "${AGGREGATED_ROLES[@]}"; do
  [[ -z "$(kubectl get clusterrole "${role}" --ignore-not-found -o name)" ]]
done

# 5. Reinstall. Helm applies the bundled definitions again as field manager
#    helm; their content is unchanged here, so their identifiers must not change.
./tests/spark_helm_install.sh
[[ "$(definition_identifiers)" == "${DEFINITION_IDENTIFIERS_BEFORE}" ]]
for role in "${AGGREGATED_ROLES[@]}"; do
  kubectl get clusterrole "${role}"
done

# 6. The operator reconciles again: a new application completes.
sed "s/^  name: ${RETAINED_APPLICATION}\$/  name: ${NEW_APPLICATION}/" "${SPARK_APPLICATION_YAML}" \
  | kubectl -n "${NAMESPACE}" apply -f -
wait_for_application_state "${NEW_APPLICATION}" COMPLETED

# 7. The new controller reconciles the retained application. A completed
# application stays completed on its own, so change its specification: the
# controller submits it again, which changes status.submissionID, and it
# completes with the same identity.
[[ "$(kubectl -n "${NAMESPACE}" get sparkapplication "${RETAINED_APPLICATION}" \
  -o jsonpath='{.status.applicationState.state}={.status.submissionID}')" \
  == "COMPLETED=${SUBMISSION_IDENTIFIER_BEFORE}" ]]
kubectl -n "${NAMESPACE}" patch sparkapplication "${RETAINED_APPLICATION}" \
  --type merge --patch '{"spec":{"arguments":["2"]}}'
wait_for_new_submission "${RETAINED_APPLICATION}" "${SUBMISSION_IDENTIFIER_BEFORE}"
wait_for_application_state "${RETAINED_APPLICATION}" COMPLETED
[[ "$(kubectl -n "${NAMESPACE}" get sparkapplication "${RETAINED_APPLICATION}" \
  -o jsonpath='{.metadata.uid}')" == "${APPLICATION_IDENTIFIER_BEFORE}" ]]
kubectl -n "${NAMESPACE}" get events \
  --field-selector "involvedObject.name=${RETAINED_APPLICATION}" --sort-by=.lastTimestamp

echo "Spark Operator Helm lifecycle verified: definitions and SparkApplication ${APPLICATION_IDENTIFIER_BEFORE} retained, operator and aggregated roles deleted and restored, reconciliation resumed."
