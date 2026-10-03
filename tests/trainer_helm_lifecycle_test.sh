#!/usr/bin/env bash
# Test installed Trainer releases on a disposable cluster. The full Helm workflow
# runs this fixed sequence after application tests, reusing its Kind cluster.
# Evidence goes to logs/trainer-lifecycle; fixtures stay until cluster teardown.
set -euxo pipefail

: "${KUBECONFIG:?Provide the disposable cluster kubeconfig explicitly}"
if [[ "${TRAINER_HELM_LIFECYCLE_DISPOSABLE:-}" != true ]]; then
  echo 'Set TRAINER_HELM_LIFECYCLE_DISPOSABLE=true only for a disposable cluster.' >&2
  exit 1
fi

TEST_NAMESPACE=${1:-kubeflow-user-example-com}
if [[ $# -gt 1 ]]; then
  echo 'Usage: trainer_helm_lifecycle_test.sh [profile namespace]' >&2
  exit 1
fi

if [[ -n "${TRAINER_APIS_CHART:-}" ]]; then
  if [[ ! -e "$TRAINER_APIS_CHART" ]]; then
    echo "ERROR: TRAINER_APIS_CHART names ${TRAINER_APIS_CHART}, which does not exist." >&2
    exit 1
  fi
  TRAINER_APIS_CHART=$(realpath "$TRAINER_APIS_CHART")
  export TRAINER_APIS_CHART
fi
REPOSITORY_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPOSITORY_ROOT"

RELEASE_NAMESPACE=kubeflow-system
API_CHART=${TRAINER_APIS_CHART:-applications/trainer/helm-crds}
DEFINITIONS=(
  clustertrainingruntimes.trainer.kubeflow.org
  trainingruntimes.trainer.kubeflow.org
  trainjobs.trainer.kubeflow.org
  jobsets.jobset.x-k8s.io
)
WEBHOOK_CONFIGURATIONS=(
  mutatingwebhookconfiguration/defaulter.trainer.kubeflow.org
  mutatingwebhookconfiguration/jobset-mutating-webhook-configuration
  validatingwebhookconfiguration/validator.trainer.kubeflow.org
  validatingwebhookconfiguration/jobset-validating-webhook-configuration
)
CONTROLLER_DEPLOYMENTS=(kubeflow-trainer-controller-manager jobset-controller-manager)
CATALOG_RUNTIME=torch-distributed
CATALOG_IMAGE_PATH='{.spec.template.spec.replicatedJobs[0].template.spec.template.spec.containers[0].image}'
LIFECYCLE_ANNOTATION_PATH='{.spec.template.metadata.annotations.trainer\.kubeflow\.org/lifecycle-test}'

RUN_IDENTIFIER="$(date +%s)-$((RANDOM % 10000))"
NAME_PREFIX="trainer-lifecycle-${RUN_IDENTIFIER}"
ADMINISTRATOR_RUNTIME="${NAME_PREFIX}-administrator"
NAMESPACED_RUNTIME="${NAME_PREFIX}-namespaced"
CATALOG_JOB="${NAME_PREFIX}-catalog-job"
NAMESPACED_JOB="${NAME_PREFIX}-namespaced-job"

EVIDENCE_DIRECTORY=${EVIDENCE_DIRECTORY:-logs/trainer-lifecycle}
mkdir -p "$EVIDENCE_DIRECTORY"
TEMPORARY_DIRECTORY=$(mktemp -d)

capture_diagnostics() {
  local directory="${EVIDENCE_DIRECTORY}/$1" namespace pod
  mkdir -p "$directory"
  for namespace in "$RELEASE_NAMESPACE" "$TEST_NAMESPACE"; do
    kubectl --request-timeout=10s get pods,deployments,services -n "$namespace" -o yaml \
      >"$directory/$namespace-resources.yaml" 2>&1 || true
    kubectl --request-timeout=10s get events -n "$namespace" --sort-by=.metadata.creationTimestamp \
      >"$directory/$namespace-events.txt" 2>&1 || true
    while IFS= read -r pod; do
      [[ -n "$pod" ]] || continue
      kubectl --request-timeout=10s logs -n "$namespace" "$pod" --all-containers=true --tail=200 \
        >"$directory/$namespace-${pod#pod/}.log" 2>&1 || true
    done < <(kubectl --request-timeout=10s get pods -n "$namespace" -o name \
      2>"$directory/$namespace-pod-list-errors.txt")
  done
  kubectl --request-timeout=10s get trainjobs,trainingruntimes,jobsets,configmaps -n "$TEST_NAMESPACE" -o yaml \
    >"$directory/training-resources.yaml" 2>&1 || true
}

finish() {
  local status=$?
  trap - EXIT
  if [[ "$status" -ne 0 ]]; then
    capture_diagnostics failure || true
  fi
  rm -rf "$TEMPORARY_DIRECTORY" || true
  exit "$status"
}
trap finish EXIT

RECORDED_OBJECTS=()
declare -A RECORDED_UIDS=()
declare -A RECORDED_SNAPSHOT_DIGESTS=()
FIXTURES_CREATED=false

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

proved() {
  echo "PROVED: $*" | tee -a "${EVIDENCE_DIRECTORY}/summary.txt"
}

uid() {
  kubectl get "$1" ${2:+--namespace "$2"} -o jsonpath='{.metadata.uid}'
}

object_exists() {
  local found
  found=$(kubectl get "$1" ${2:+--namespace "$2"} --ignore-not-found -o name) ||
    fail "$1 could not be read, which is no evidence that it is absent.${3:+ $3}"
  [[ -n "$found" ]]
}

# kubectl create refuses an existing name; fixtures stay for cluster teardown.
create_fixture() {
  kubectl create ${2:+--namespace "$2"} -f "$1"
}

record_identity() {
  local resource="$1" namespace="${2:-}" recorded
  recorded=$(uid "$resource" "$namespace")
  [[ -n "$recorded" ]] || fail "${resource} has no UID."
  RECORDED_OBJECTS+=("${resource}|${namespace}")
  RECORDED_UIDS["${resource}|${namespace}"]=$recorded
  echo "${resource} ${namespace:-cluster-scoped} ${recorded}" >>"${EVIDENCE_DIRECTORY}/identities.txt"
}

assert_uid() {
  local resource="$1" expected="$2" namespace="${3:-}" operation="$4" actual
  actual=$(uid "$resource" "$namespace") || fail "${resource} is not readable after ${operation}."
  [[ "$actual" == "$expected" ]] ||
    fail "${resource} has the UID ${actual} after ${operation}, recorded was ${expected}."
}

snapshot_runtime() {
  kubectl get "configmap/$1-runtime-snapshot" --namespace "$TEST_NAMESPACE" \
    -o jsonpath='{.data.runtime}'
}

snapshot_digest() {
  snapshot_runtime "$1" | sha256sum | cut -d ' ' -f 1
}

assert_identities_retained() {
  local operation="$1" key resource namespace job actual
  for key in "${RECORDED_OBJECTS[@]}"; do
    IFS='|' read -r resource namespace <<<"$key"
    assert_uid "$resource" "${RECORDED_UIDS[$key]}" "$namespace" "$operation"
  done
  for job in "${!RECORDED_SNAPSHOT_DIGESTS[@]}"; do
    actual=$(snapshot_digest "$job")
    [[ "$actual" == "${RECORDED_SNAPSHOT_DIGESTS[$job]}" ]] ||
      fail "The runtime snapshot of ${job} changed its content after ${operation}."
  done
  echo "retained after ${operation}: ${#RECORDED_OBJECTS[@]} identities, ${#RECORDED_SNAPSHOT_DIGESTS[@]} snapshot contents" |
    tee -a "${EVIDENCE_DIRECTORY}/identities.txt"
}

write_train_job_manifest() {
  local manifest="$1" name="$2" runtime_kind="$3" runtime_name="$4"
  cat >"$manifest" <<EOF
apiVersion: trainer.kubeflow.org/v1alpha1
kind: TrainJob
metadata:
  name: ${name}
spec:
  suspend: true
  runtimeRef:
    apiGroup: trainer.kubeflow.org
    kind: ${runtime_kind}
    name: ${runtime_name}
  trainer:
    numNodes: 1
    command: ["python", "-c", "print('trainer lifecycle fixture')"]
EOF
}

create_reconciled_train_job() {
  local name="$1" runtime_kind="$2" runtime_name="$3" job_uid owner_uid
  write_train_job_manifest "${TEMPORARY_DIRECTORY}/${name}.yaml" "$name" "$runtime_kind" "$runtime_name"
  create_fixture "${TEMPORARY_DIRECTORY}/${name}.yaml" "$TEST_NAMESPACE"
  kubectl wait --namespace "$TEST_NAMESPACE" --for=create \
    "configmap/${name}-runtime-snapshot" --timeout=180s
  kubectl wait --namespace "$TEST_NAMESPACE" --for=create "jobset/${name}" --timeout=180s
  job_uid=$(uid "trainjob/${name}" "$TEST_NAMESPACE")
  owner_uid=$(kubectl get "jobset/${name}" --namespace "$TEST_NAMESPACE" \
    -o jsonpath='{.metadata.ownerReferences[0].uid}')
  [[ -n "$job_uid" && "$owner_uid" == "$job_uid" ]] ||
    fail "The JobSet ${name} is not owned by the TrainJob ${name}."
}

record_reconciled_train_job() {
  record_identity "trainjob/$1" "$TEST_NAMESPACE"
  record_identity "configmap/$1-runtime-snapshot" "$TEST_NAMESPACE"
  record_identity "jobset/$1" "$TEST_NAMESPACE"
  RECORDED_SNAPSHOT_DIGESTS["$1"]=$(snapshot_digest "$1")
}

ensure_fixtures() {
  local definition
  if [[ "$FIXTURES_CREATED" == true ]]; then
    return
  fi
  record_identity "namespace/${RELEASE_NAMESPACE}"
  for definition in "${DEFINITIONS[@]}"; do
    record_identity "crd/${definition}"
  done

  # Both runtime fixtures copy the specification of the live catalog runtime. The
  # administrator runtime has its own name and is no resource of any release.
  kubectl get "clustertrainingruntime/${CATALOG_RUNTIME}" -o json \
    >"${TEMPORARY_DIRECTORY}/catalog-runtime.json"
  python3 - "$TEMPORARY_DIRECTORY" "$ADMINISTRATOR_RUNTIME" "$NAMESPACED_RUNTIME" <<'PY'
import json
import sys
from pathlib import Path

directory = Path(sys.argv[1])
catalog = json.loads((directory / "catalog-runtime.json").read_text())
for kind, name in (
    ("ClusterTrainingRuntime", sys.argv[2]),
    ("TrainingRuntime", sys.argv[3]),
):
    fixture = {
        "apiVersion": catalog["apiVersion"],
        "kind": kind,
        "metadata": {"name": name},
        "spec": catalog["spec"],
    }
    (directory / f"{name}.json").write_text(json.dumps(fixture))
PY
  create_fixture "${TEMPORARY_DIRECTORY}/${ADMINISTRATOR_RUNTIME}.json"
  record_identity "clustertrainingruntime/${ADMINISTRATOR_RUNTIME}"
  create_fixture "${TEMPORARY_DIRECTORY}/${NAMESPACED_RUNTIME}.json" "$TEST_NAMESPACE"
  record_identity "trainingruntime/${NAMESPACED_RUNTIME}" "$TEST_NAMESPACE"

  create_reconciled_train_job "$CATALOG_JOB" ClusterTrainingRuntime "$CATALOG_RUNTIME"
  record_reconciled_train_job "$CATALOG_JOB"
  create_reconciled_train_job "$NAMESPACED_JOB" TrainingRuntime "$NAMESPACED_RUNTIME"
  record_reconciled_train_job "$NAMESPACED_JOB"
  snapshot_runtime "$NAMESPACED_JOB" | python3 -c '
import sys
import yaml

runtime = yaml.safe_load(sys.stdin)
found = (runtime["kind"], runtime["metadata"]["name"])
assert found == ("TrainingRuntime", sys.argv[1]), found
' "$NAMESPACED_RUNTIME"
  FIXTURES_CREATED=true
}

expect_admission_denial() {
  local runtime_name="$1" output="${EVIDENCE_DIRECTORY}/denial.txt"
  shift
  if "$@" >"$output" 2>&1; then
    cat "$output"
    fail "Admitted although the runtime ${runtime_name} is absent: $*"
  fi
  cat "$output"
  grep -Eiq 'admission webhook.*denied|denied the request' "$output" ||
    fail "The failure is not an admission denial: $*"
  grep -Fq "$runtime_name" "$output" ||
    fail "The admission denial does not name the runtime ${runtime_name}: $*"
  {
    echo "denied: $*"
    cat "$output"
  } >>"${EVIDENCE_DIRECTORY}/admission-denials.txt"
}

assert_admission_works() {
  local absent_runtime="${NAME_PREFIX}-absent-runtime"
  write_train_job_manifest "${TEMPORARY_DIRECTORY}/probe-absent.yaml" \
    "${NAME_PREFIX}-probe" ClusterTrainingRuntime "$absent_runtime"
  expect_admission_denial "$absent_runtime" kubectl create --namespace "$TEST_NAMESPACE" \
    --dry-run=server -f "${TEMPORARY_DIRECTORY}/probe-absent.yaml"
  write_train_job_manifest "${TEMPORARY_DIRECTORY}/probe-present.yaml" \
    "${NAME_PREFIX}-probe" ClusterTrainingRuntime "$CATALOG_RUNTIME"
  kubectl create --namespace "$TEST_NAMESPACE" --dry-run=server \
    -f "${TEMPORARY_DIRECTORY}/probe-present.yaml"
}

current_revision() {
  helm history "$1" --namespace "$RELEASE_NAMESPACE" --output json |
    python3 -c 'import json, sys; print(json.load(sys.stdin)[-1]["revision"])'
}

assert_release_deployed() {
  helm status "$1" --namespace "$RELEASE_NAMESPACE" --output json |
    python3 -c 'import json, sys; status = json.load(sys.stdin)["info"]["status"]; assert status == "deployed", status'
}

wait_for_established_definitions() {
  local definition
  for definition in "${DEFINITIONS[@]}"; do
    kubectl wait --for=condition=Established "crd/${definition}" --timeout=120s
  done
}

retire_catalog() {
  capture_diagnostics before-catalog-uninstall
  helm uninstall trainer-runtimes --namespace "$RELEASE_NAMESPACE" --wait --timeout 5m
  if object_exists "clustertrainingruntime/${CATALOG_RUNTIME}"; then
    fail "${CATALOG_RUNTIME} is still present after the catalog was uninstalled."
  fi
}

restore_catalog() {
  ./tests/trainer_helm_install.sh trainer-runtimes
  assert_release_deployed trainer-runtimes
  echo "${CATALOG_RUNTIME} is back with the UID $(uid "clustertrainingruntime/${CATALOG_RUNTIME}")."
}

scenario_controller_upgrade_rollback() {
  local catalog_runtime_uid previous_revision deployment annotation
  ensure_fixtures
  catalog_runtime_uid=$(uid "clustertrainingruntime/${CATALOG_RUNTIME}")
  # A changed Pod template, not an unchanged upgrade, exercises rollout and rollback.
  cp -R applications/trainer/helm "${TEMPORARY_DIRECTORY}/controller"
  python3 - "${TEMPORARY_DIRECTORY}/controller/manifests/platform-resources.yaml" "$RUN_IDENTIFIER" <<'PY'
import sys
from pathlib import Path

import yaml

path = Path(sys.argv[1])
resources = list(yaml.safe_load_all(path.read_text()))
for resource in resources:
    if resource and resource["kind"] == "Deployment":
        resource["spec"]["template"]["metadata"].setdefault("annotations", {})[
            "trainer.kubeflow.org/lifecycle-test"
        ] = sys.argv[2]
path.write_text(yaml.safe_dump_all(resources, sort_keys=False))
PY
  cp "${TEMPORARY_DIRECTORY}/controller/manifests/platform-resources.yaml" "${EVIDENCE_DIRECTORY}/controller-candidate.yaml"
  previous_revision=$(current_revision trainer)
  capture_diagnostics before-controller-upgrade
  helm upgrade trainer "${TEMPORARY_DIRECTORY}/controller" \
    --namespace "$RELEASE_NAMESPACE" --wait --timeout 10m
  assert_release_deployed trainer
  for deployment in "${CONTROLLER_DEPLOYMENTS[@]}"; do
    annotation=$(kubectl get "deployment/${deployment}" --namespace "$RELEASE_NAMESPACE" \
      -o "jsonpath=${LIFECYCLE_ANNOTATION_PATH}")
    [[ "$annotation" == "$RUN_IDENTIFIER" ]] ||
      fail "deployment/${deployment} does not carry the changed Pod template."
  done
  assert_identities_retained "the changed upgrade of trainer"
  assert_admission_works

  capture_diagnostics before-controller-rollback
  helm rollback trainer "$previous_revision" --namespace "$RELEASE_NAMESPACE" --wait --timeout 10m
  assert_release_deployed trainer
  for deployment in "${CONTROLLER_DEPLOYMENTS[@]}"; do
    annotation=$(kubectl get "deployment/${deployment}" --namespace "$RELEASE_NAMESPACE" \
      -o "jsonpath=${LIFECYCLE_ANNOTATION_PATH}")
    [[ -z "$annotation" ]] ||
      fail "deployment/${deployment} still carries the changed Pod template after the rollback."
  done
  assert_identities_retained "the rollback of trainer"
  assert_uid "clustertrainingruntime/${CATALOG_RUNTIME}" "$catalog_runtime_uid" "" "the rollback of trainer"
  assert_admission_works
  proved "controller-upgrade-rollback: a changed rollout and its rollback keep every recorded identity and the catalog; admission works afterwards."
}

scenario_controller_reinstall() {
  local catalog_runtime_uid webhook
  ensure_fixtures
  catalog_runtime_uid=$(uid "clustertrainingruntime/${CATALOG_RUNTIME}")
  capture_diagnostics before-controller-uninstall
  helm uninstall trainer --namespace "$RELEASE_NAMESPACE" --wait --timeout 5m
  # A webhook configuration without its service would deny every request.
  for webhook in "${WEBHOOK_CONFIGURATIONS[@]}"; do
    if object_exists "$webhook"; then
      fail "${webhook} is still present after trainer was uninstalled."
    fi
  done
  assert_release_deployed trainer-apis
  assert_release_deployed trainer-runtimes
  assert_identities_retained "the uninstallation of trainer"
  assert_uid "clustertrainingruntime/${CATALOG_RUNTIME}" "$catalog_runtime_uid" "" "the uninstallation of trainer"

  ./tests/trainer_helm_install.sh trainer
  assert_release_deployed trainer
  assert_identities_retained "the reinstallation of trainer"
  assert_uid "clustertrainingruntime/${CATALOG_RUNTIME}" "$catalog_runtime_uid" "" "the reinstallation of trainer"
  # Retained status alone would not establish that the controllers work again.
  assert_admission_works
  proved "controller-reinstall: the webhook configurations leave with trainer; the definitions, the catalog, the namespace and every recorded identity stay; admission works after the reinstallation."
}

scenario_api_reinstall() {
  local definition owner
  ensure_fixtures
  capture_diagnostics before-api-uninstall
  helm uninstall trainer-apis --namespace "$RELEASE_NAMESPACE" --wait --timeout 5m
  assert_identities_retained "the uninstallation of trainer-apis"

  ./tests/trainer_helm_install.sh trainer-apis
  assert_release_deployed trainer-apis
  for definition in "${DEFINITIONS[@]}"; do
    owner=$(kubectl get "crd/${definition}" \
      -o 'jsonpath={.metadata.annotations.meta\.helm\.sh/release-name}')
    [[ "$owner" == trainer-apis ]] || fail "crd/${definition} belongs to the release ${owner}."
  done
  assert_identities_retained "the reinstallation of trainer-apis"
  # The release must manage the retained definitions again, not only name them.
  helm upgrade trainer-apis "$API_CHART" --namespace "$RELEASE_NAMESPACE" --wait --timeout 5m
  assert_release_deployed trainer-apis
  wait_for_established_definitions
  assert_identities_retained "the upgrade of the reinstalled trainer-apis"
  assert_admission_works
  proved "api-reinstall: the four definitions, TrainJobs, both runtime kinds, snapshots and JobSets are retained without trainer-apis; the same release name takes the definitions back and upgrades them."
}

scenario_catalog_update_rollback() {
  local catalog_runtime_uid original_specification restored_specification changed_image live_image
  local previous_revision updated_job="${NAME_PREFIX}-updated-job"
  ensure_fixtures
  catalog_runtime_uid=$(uid "clustertrainingruntime/${CATALOG_RUNTIME}")
  original_specification=$(kubectl get "clustertrainingruntime/${CATALOG_RUNTIME}" -o 'jsonpath={.spec}')
  cp -R applications/trainer/helm-runtimes "${TEMPORARY_DIRECTORY}/runtimes"
  changed_image=$(
    python3 - "${TEMPORARY_DIRECTORY}/runtimes/manifests/platform-resources.yaml" "$CATALOG_RUNTIME" <<'PY'
import sys
from pathlib import Path

import yaml

path = Path(sys.argv[1])
resources = list(yaml.safe_load_all(path.read_text()))
changed = []
for resource in resources:
    if resource and resource["metadata"]["name"] == sys.argv[2]:
        for job in resource["spec"]["template"]["spec"]["replicatedJobs"]:
            for container in job["template"]["spec"]["template"]["spec"]["containers"]:
                container["image"] += "-trainer-helm-lifecycle-test"
                changed.append(container["image"])
assert len(changed) == 1, changed
path.write_text(yaml.safe_dump_all(resources, sort_keys=False))
print(changed[0])
PY
  )
  cp "${TEMPORARY_DIRECTORY}/runtimes/manifests/platform-resources.yaml" "${EVIDENCE_DIRECTORY}/runtime-candidate.yaml"
  previous_revision=$(current_revision trainer-runtimes)
  capture_diagnostics before-catalog-upgrade
  helm upgrade trainer-runtimes "${TEMPORARY_DIRECTORY}/runtimes" \
    --namespace "$RELEASE_NAMESPACE" --wait --timeout 5m
  assert_release_deployed trainer-runtimes
  live_image=$(kubectl get "clustertrainingruntime/${CATALOG_RUNTIME}" -o "jsonpath=${CATALOG_IMAGE_PATH}")
  [[ "$live_image" == "$changed_image" ]] ||
    fail "${CATALOG_RUNTIME} has the image ${live_image} after the catalog update."
  assert_uid "clustertrainingruntime/${CATALOG_RUNTIME}" "$catalog_runtime_uid" "" "the catalog update"
  # The snapshot of the earlier TrainJob must keep its content.
  assert_identities_retained "the update of trainer-runtimes"
  create_reconciled_train_job "$updated_job" ClusterTrainingRuntime "$CATALOG_RUNTIME"
  snapshot_runtime "$updated_job" | grep -F -- "$changed_image" ||
    fail "The snapshot of the new TrainJob does not hold the changed image."
  kubectl get "jobset/${updated_job}" --namespace "$TEST_NAMESPACE" -o json |
    grep -F -- "$changed_image" || fail "The JobSet of the new TrainJob does not hold the changed image."
  record_reconciled_train_job "$updated_job"

  capture_diagnostics before-catalog-rollback
  helm rollback trainer-runtimes "$previous_revision" \
    --namespace "$RELEASE_NAMESPACE" --wait --timeout 5m
  assert_release_deployed trainer-runtimes
  restored_specification=$(kubectl get "clustertrainingruntime/${CATALOG_RUNTIME}" -o 'jsonpath={.spec}')
  [[ "$restored_specification" == "$original_specification" ]] ||
    fail "The rollback did not restore the specification of ${CATALOG_RUNTIME}."
  assert_uid "clustertrainingruntime/${CATALOG_RUNTIME}" "$catalog_runtime_uid" "" "the catalog rollback"
  # A rollback restores the catalog; it does not rewrite a captured snapshot.
  assert_identities_retained "the rollback of trainer-runtimes"
  proved "catalog-update-rollback: a new TrainJob resolved the changed image; the earlier snapshot kept its content; the rollback restored the live specification of ${CATALOG_RUNTIME}; the snapshot of the new TrainJob kept the changed image."
}

scenario_retirement_after_snapshot() {
  ensure_fixtures
  retire_catalog
  assert_identities_retained "the uninstallation of trainer-runtimes"
  expect_admission_denial "$CATALOG_RUNTIME" kubectl patch "trainjob/${CATALOG_JOB}" \
    --namespace "$TEST_NAMESPACE" --type merge -p '{"spec":{"suspend":false}}'
  # The catalog does not own the namespaced runtime: its TrainJob stays updatable.
  kubectl patch "trainjob/${NAMESPACED_JOB}" --namespace "$TEST_NAMESPACE" \
    --type merge -p '{"spec":{"suspend":false}}' --dry-run=server

  restore_catalog
  kubectl patch "trainjob/${CATALOG_JOB}" --namespace "$TEST_NAMESPACE" \
    --type merge -p '{"spec":{"suspend":false}}' --dry-run=server
  assert_identities_retained "the reinstallation of trainer-runtimes"
  proved "retirement-after-snapshot: with a snapshot, a validated update is denied by admission while ${CATALOG_RUNTIME} is absent and admitted after the catalog returned; the administrator runtime, the namespaced runtime, the TrainJobs, snapshots and JobSets stayed."
}

for release in trainer-apis trainer trainer-runtimes; do
  assert_release_deployed "$release"
done
kubectl get namespace "$RELEASE_NAMESPACE"
kubectl get namespace "$TEST_NAMESPACE"

scenario_controller_upgrade_rollback
scenario_catalog_update_rollback
scenario_api_reinstall
scenario_retirement_after_snapshot
scenario_controller_reinstall
./tests/trainer_test.sh "$TEST_NAMESPACE"
capture_diagnostics recovered
proved "All release operations passed and SDK training completed after recovery. Evidence: ${EVIDENCE_DIRECTORY}"
