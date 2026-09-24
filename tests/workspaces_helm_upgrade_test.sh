#!/usr/bin/env bash
# Upgrade and rollback evidence for the Kubeflow Workspaces Helm chart
# (applications/workspaces/helm). It is not part of a workflow; it needs a
# cluster on which the kubeflow-workspaces release is deployed, for example by
# tests/workspaces_helm_install.sh.
#
# WORKSPACES_UPGRADE_CHART names a copy of the chart whose payload differs, for
# example in a controller argument. No helm command below passes a force option.
#
# 1. helm upgrade with the chart of this checkout, which is an unchanged upgrade
#    when the release was installed from it.
# 2. helm upgrade with the changed chart.
# 3. helm rollback to the revision of step 1, never to a revision that was
#    stored before this script started. The release manifest must be the one of
#    step 1 again.
#
# After each step the new revision must be deployed, and the aggregated
# ClusterRoles kubeflow-workspaces-admin, -edit and -view must carry rules
# without helm among the managers of .rules, which belongs to the aggregation
# controller. A ServiceAccount bound to kubeflow-workspaces-edit must still be
# allowed to create a Workspace in its namespace, and must still not be allowed
# to read a Secret there.
#
# That ServiceAccount and its RoleBinding live in a namespace that this script
# creates and that is named uniquely for every run, unless
# WORKSPACES_UPGRADE_AUTHORIZATION_NAMESPACE names it. The script deletes only a
# namespace that it has created: when the namespace already exists, the script
# fails and leaves that namespace untouched.
set -euxo pipefail

CHANGED_CHART="${WORKSPACES_UPGRADE_CHART:?set it to a copy of applications/workspaces/helm with a changed payload}"
EVIDENCE_DIRECTORY="${EVIDENCE_DIRECTORY:-$(mktemp -d)}"
RELEASE_NAME="kubeflow-workspaces"
RELEASE_NAMESPACE="kubeflow"
CHART="applications/workspaces/helm"
AGGREGATED_ROLES=(kubeflow-workspaces-admin kubeflow-workspaces-edit kubeflow-workspaces-view)
AUTHORIZATION_NAMESPACE="${WORKSPACES_UPGRADE_AUTHORIZATION_NAMESPACE:-workspaces-upgrade-test-$(date +%s)-${RANDOM}}"
EDITOR_SERVICE_ACCOUNT="workspaces-editor"

mkdir -p "${EVIDENCE_DIRECTORY}"
echo "Evidence is written to ${EVIDENCE_DIRECTORY}"

render_chart() {
  helm template "${RELEASE_NAME}" "$1" --namespace "${RELEASE_NAMESPACE}" \
    --values "$1/ci/values-istio.yaml"
}

aggregated_rule_count() {
  kubectl get clusterrole "$1" -o json | jq '.rules // [] | length'
}

# Records the release manifest of the expected revision and asserts the state
# that every step has to leave behind.
assert_release_and_aggregated_roles() {
  local label="$1"
  local expected_revision="$2"
  local role
  local role_file
  local secret_answer
  helm history "${RELEASE_NAME}" --namespace "${RELEASE_NAMESPACE}" \
    | tee "${EVIDENCE_DIRECTORY}/${label}-history.txt"
  helm status "${RELEASE_NAME}" --namespace "${RELEASE_NAMESPACE}" -o json \
    | jq -e --argjson revision "${expected_revision}" \
      '.version == $revision and .info.status == "deployed"'
  helm get manifest "${RELEASE_NAME}" --namespace "${RELEASE_NAMESPACE}" \
    --revision "${expected_revision}" >"${EVIDENCE_DIRECTORY}/${label}-manifest.yaml"
  for role in "${AGGREGATED_ROLES[@]}"; do
    role_file="${EVIDENCE_DIRECTORY}/${label}-${role}.json"
    kubectl get clusterrole "${role}" --show-managed-fields -o json >"${role_file}"
    jq -e '.rules // [] | length > 0' "${role_file}"
    jq -c '[.metadata.managedFields[] | select(.fieldsV1 | has("f:rules")) | .manager]' "${role_file}"
    jq -e 'any(.metadata.managedFields[]; .manager == "helm" and (.fieldsV1 | has("f:rules"))) | not' \
      "${role_file}"
  done
  kubectl auth can-i create workspaces.kubeflow.org \
    --as="system:serviceaccount:${AUTHORIZATION_NAMESPACE}:${EDITOR_SERVICE_ACCOUNT}" \
    -n "${AUTHORIZATION_NAMESPACE}" | grep -qx yes
  # kubectl auth can-i exits with 1 when the answer is no.
  secret_answer="$(kubectl auth can-i get secrets \
    --as="system:serviceaccount:${AUTHORIZATION_NAMESPACE}:${EDITOR_SERVICE_ACCOUNT}" \
    -n "${AUTHORIZATION_NAMESPACE}" || true)"
  [[ "${secret_answer}" == "no" ]]
}

render_chart "${CHART}" >"${EVIDENCE_DIRECTORY}/chart-render.yaml"
render_chart "${CHANGED_CHART}" >"${EVIDENCE_DIRECTORY}/changed-chart-render.yaml"
if diff "${EVIDENCE_DIRECTORY}/chart-render.yaml" "${EVIDENCE_DIRECTORY}/changed-chart-render.yaml" \
  >"${EVIDENCE_DIRECTORY}/changed-chart-difference.txt"; then
  echo "Error, ${CHANGED_CHART} renders the same manifest as ${CHART}."
  exit 1
fi

# The cleanup is registered only after this run has created the namespace. A
# failed creation, for example of a namespace that already exists, ends the
# script here, before anything could delete a namespace that this run does not
# own.
kubectl create namespace "${AUTHORIZATION_NAMESPACE}"
trap 'kubectl delete namespace "${AUTHORIZATION_NAMESPACE}" --ignore-not-found' EXIT
kubectl create serviceaccount "${EDITOR_SERVICE_ACCOUNT}" -n "${AUTHORIZATION_NAMESPACE}"
kubectl create rolebinding "${EDITOR_SERVICE_ACCOUNT}" -n "${AUTHORIZATION_NAMESPACE}" \
  --clusterrole=kubeflow-workspaces-edit \
  --serviceaccount="${AUTHORIZATION_NAMESPACE}:${EDITOR_SERVICE_ACCOUNT}"

# The aggregation controller fills the rules shortly after an installation.
for role in "${AGGREGATED_ROLES[@]}"; do
  deadline=$((SECONDS + 60))
  until [[ "$(aggregated_rule_count "${role}")" -gt 0 ]]; do
    if ((SECONDS >= deadline)); then
      echo "Error, the aggregation controller did not fill the rules of ${role}."
      exit 1
    fi
    sleep 5
  done
done
INITIAL_REVISION="$(helm status "${RELEASE_NAME}" --namespace "${RELEASE_NAMESPACE}" -o json \
  | jq -r '.version')"
UNCHANGED_REVISION=$((INITIAL_REVISION + 1))
CHANGED_REVISION=$((INITIAL_REVISION + 2))
ROLLBACK_REVISION=$((INITIAL_REVISION + 3))
assert_release_and_aggregated_roles before-upgrade "${INITIAL_REVISION}"

echo "Upgrade with the chart of this checkout ..."
helm upgrade "${RELEASE_NAME}" "${CHART}" --namespace "${RELEASE_NAMESPACE}" \
  --values "${CHART}/ci/values-istio.yaml" --wait --timeout 5m
assert_release_and_aggregated_roles unchanged-upgrade "${UNCHANGED_REVISION}"

echo "Upgrade with the changed chart ..."
helm upgrade "${RELEASE_NAME}" "${CHANGED_CHART}" --namespace "${RELEASE_NAMESPACE}" \
  --values "${CHANGED_CHART}/ci/values-istio.yaml" --wait --timeout 5m
assert_release_and_aggregated_roles changed-upgrade "${CHANGED_REVISION}"
if diff "${EVIDENCE_DIRECTORY}/unchanged-upgrade-manifest.yaml" \
  "${EVIDENCE_DIRECTORY}/changed-upgrade-manifest.yaml" \
  >"${EVIDENCE_DIRECTORY}/changed-upgrade-difference.txt"; then
  echo "Error, the changed upgrade stored the manifest of the unchanged upgrade."
  exit 1
fi

echo "Rollback to the revision of the first upgrade ..."
helm rollback "${RELEASE_NAME}" "${UNCHANGED_REVISION}" --namespace "${RELEASE_NAMESPACE}" \
  --wait --timeout 5m
assert_release_and_aggregated_roles rollback "${ROLLBACK_REVISION}"
diff "${EVIDENCE_DIRECTORY}/unchanged-upgrade-manifest.yaml" "${EVIDENCE_DIRECTORY}/rollback-manifest.yaml"

echo "Workspaces Helm upgrade test completed. Evidence: ${EVIDENCE_DIRECTORY}"
