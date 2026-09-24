#!/usr/bin/env bash
# Lifecycle test of the three Trainer Helm releases (trainer-apis, trainer and
# trainer-runtimes) on an explicitly selected disposable cluster. No workflow
# runs this script.
#
# Requirements: KUBECONFIG names the cluster and
# TRAINER_HELM_LIFECYCLE_DISPOSABLE=true confirms that it is disposable. The
# three releases are deployed by tests/trainer_helm_install.sh, the profile
# namespace exists, and Helm 4, kubectl and python3 with PyYAML are available.
#
# Usage:
#   ./tests/trainer_helm_lifecycle_test.sh [profile namespace [scenario ...]]
# TRAINER_HELM_LIFECYCLE_SCENARIOS names the scenarios, separated by spaces, when
# no argument does. Without any selection only the scenario smoke runs, which
# changes no release. The name all selects every scenario in the order below.
#
# Scenario                     Changes on the cluster, and what a pass proves
# smoke                        One SDK TrainJob of tests/trainer_test.sh, which
#                              that script leaves in place. Proves admission over
#                              the webhook (a TrainJob with an absent runtime is
#                              denied, one with torch-distributed is admitted)
#                              and a completed SDK TrainJob.
# fixtures                     Only the fixtures described below. Proves that a
#                              namespaced TrainingRuntime and a TrainJob that uses
#                              it are admitted, and that every fixture TrainJob
#                              receives its runtime snapshot and its JobSet.
# controller-upgrade-rollback  Upgrades trainer to a copy with a changed Pod
#                              template and rolls it back. Proves the rollout, the
#                              rollback, admission and a completed SDK TrainJob
#                              afterwards.
# controller-reinstall         Uninstalls trainer and installs it again. Proves
#                              that the webhook configurations leave with the
#                              release, that the other two releases stay, and
#                              admission plus a completed SDK TrainJob afterwards.
# api-upgrade                  Upgrades trainer-apis to a copy whose TrainJob
#                              definition has one more optional property, then
#                              upgrades it back to the unchanged chart. Proves a
#                              compatible changed definition upgrade: the property
#                              is served, existing objects stay readable and a new
#                              TrainJob is admitted and reconciled. It proves
#                              nothing about other schema versions.
# api-reinstall                Uninstalls trainer-apis, installs it again and
#                              upgrades it with the unchanged chart. Proves that
#                              the four definitions and their objects are retained
#                              and that the same release name takes the retained
#                              definitions back and manages them again.
# catalog-update-rollback      Upgrades trainer-runtimes to a copy with a changed
#                              torch-distributed image and rolls it back. Proves
#                              that a new TrainJob resolves the updated runtime,
#                              that the earlier snapshot keeps its content and that
#                              the rollback restores the live runtime. Every
#                              TrainJob stays suspended; the changed image is
#                              never pulled.
# retirement-after-snapshot    Uninstalls trainer-runtimes and installs it again.
#                              Proves that a validated update of a TrainJob whose
#                              snapshot exists is denied by admission while its
#                              runtime is absent, and admitted again afterwards.
# retirement-before-snapshot   Uninstalls trainer-runtimes and installs it again.
#                              Proves the same for a TrainJob that was admitted
#                              while its runtime existed and has no snapshot, and
#                              that a new submission is denied. The TrainJob is
#                              held without a snapshot by
#                              spec.managedBy: kueue.x-k8s.io/multikueue, the API
#                              value that makes the Trainer controller skip it, so
#                              the scenario refuses a cluster with Kueue, and one
#                              whose Kueue definition cannot be read. Its snapshot
#                              and its JobSet must be absent in every read of
#                              TRAINER_HELM_LIFECYCLE_SNAPSHOT_ABSENCE_SECONDS
#                              (30) after its creation, while the runtime is
#                              absent and at the end. It does not show the
#                              reconciliation failure of a TrainJob that the
#                              Trainer controller manages.
#
# Fixtures. Every scenario except smoke creates, once per run, an administrator
# ClusterTrainingRuntime with its own name, a namespaced TrainingRuntime in the
# profile namespace, a suspended TrainJob on torch-distributed and a suspended
# TrainJob on the namespaced TrainingRuntime. It records the UID of each, of both
# runtime snapshots with a digest of their content, of both JobSets, of the four
# definitions and of the namespace kubeflow-system, and asserts all of them after
# every release operation of the scenario.
#
# Absence. An object counts as absent only when a successful read returns
# nothing. A read that fails, by authorization, connection or anything else, is
# evidence of neither presence nor absence and fails the run.
#
# Ownership. Every object name carries a run identifier. An object is created
# with kubectl create after a check that its name is free, and it is recorded as
# owned only after that creation succeeded. The exit handler is registered after
# the first recorded creation and deletes recorded objects only; snapshots and
# JobSets leave with their TrainJob. TRAINER_HELM_LIFECYCLE_KEEP_FIXTURES=true
# keeps the objects for diagnosis.
#
# Every installation of a release is a call of tests/trainer_helm_install.sh with
# the release name, so a reinstallation here cannot differ from the installer;
# TRAINER_APIS_CHART applies to it as well. No command passes a force option. A
# scenario that fails can leave a release uninstalled, upgraded to a copy or
# rolled back: use a disposable cluster. The changed charts are copies in a
# temporary directory, never the charts of this checkout.
#
# EVIDENCE_DIRECTORY receives the recorded identities, the admission denials and
# the summary of what passed; it is a new temporary directory by default.
set -euxo pipefail

: "${KUBECONFIG:?Provide the disposable cluster kubeconfig explicitly}"
if [[ "${TRAINER_HELM_LIFECYCLE_DISPOSABLE:-}" != true ]]; then
  echo 'Set TRAINER_HELM_LIFECYCLE_DISPOSABLE=true only for a disposable cluster.' >&2
  exit 1
fi

KNOWN_SCENARIOS=(
  smoke
  fixtures
  controller-upgrade-rollback
  controller-reinstall
  api-upgrade
  api-reinstall
  catalog-update-rollback
  retirement-after-snapshot
  retirement-before-snapshot
)
TEST_NAMESPACE=${1:-kubeflow-user-example-com}
if [[ $# -gt 1 ]]; then
  SELECTED_SCENARIOS=("${@:2}")
else
  read -r -a SELECTED_SCENARIOS <<<"${TRAINER_HELM_LIFECYCLE_SCENARIOS:-smoke}"
fi
if [[ "${SELECTED_SCENARIOS[*]}" == all ]]; then
  SELECTED_SCENARIOS=("${KNOWN_SCENARIOS[@]}")
fi
for scenario in "${SELECTED_SCENARIOS[@]}"; do
  if [[ " ${KNOWN_SCENARIOS[*]} " != *" ${scenario} "* ]]; then
    echo "ERROR: ${scenario} is not a scenario. Scenarios: ${KNOWN_SCENARIOS[*]}, or all alone." >&2
    exit 1
  fi
done

# As in the installer, a relative chart path belongs to the calling directory.
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
API_TEST_PROPERTY=trainerHelmLifecycleTest
EXTERNAL_MANAGER=kueue.x-k8s.io/multikueue
SNAPSHOT_ABSENCE_SECONDS=${TRAINER_HELM_LIFECYCLE_SNAPSHOT_ABSENCE_SECONDS:-30}

# JobSet v0.12.0 denies a JobSet whose Pod names would exceed 63 characters. The
# Pod of a fixture is named <TrainJob>-node-0-0-<5 characters>, so a TrainJob name
# has at most 48 characters. The longest one,
# trainer-lifecycle-<run identifier>-namespaced-job, leaves 15 for the identifier.
RUN_IDENTIFIER=${TRAINER_HELM_LIFECYCLE_RUN_IDENTIFIER:-$(date +%s)-$((RANDOM % 10000))}
if [[ ! "$RUN_IDENTIFIER" =~ ^[a-z0-9]([-a-z0-9]{0,13}[a-z0-9])?$ ]]; then
  echo "ERROR: the run identifier ${RUN_IDENTIFIER} is not a lowercase name of at most 15 characters; the JobSet of a fixture TrainJob would be denied." >&2
  exit 1
fi
NAME_PREFIX="trainer-lifecycle-${RUN_IDENTIFIER}"
ADMINISTRATOR_RUNTIME="${NAME_PREFIX}-administrator"
NAMESPACED_RUNTIME="${NAME_PREFIX}-namespaced"
CATALOG_JOB="${NAME_PREFIX}-catalog-job"
NAMESPACED_JOB="${NAME_PREFIX}-namespaced-job"

EVIDENCE_DIRECTORY=${EVIDENCE_DIRECTORY:-$(mktemp -d)}
mkdir -p "$EVIDENCE_DIRECTORY"
TEMPORARY_DIRECTORY=$(mktemp -d)
trap 'rm -rf "$TEMPORARY_DIRECTORY"' EXIT

OWNED_OBJECTS=()
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

# Succeeds when a successful read returns the object and returns 1 when a
# successful read returns nothing. A read that fails is evidence of neither, so it
# fails the run instead of counting as absence; no error text is interpreted. The
# optional third argument says what stays unknown then.
object_exists() {
  local found
  found=$(kubectl get "$1" ${2:+--namespace "$2"} --ignore-not-found -o name) ||
    fail "$1 could not be read, which is no evidence that it is absent.${3:+ $3}"
  [[ -n "$found" ]]
}

# Deletes what this run has recorded as created, the newest object first, and
# nothing else.
delete_owned_objects() {
  local index resource namespace
  for ((index = ${#OWNED_OBJECTS[@]} - 1; index >= 0; index--)); do
    IFS='|' read -r resource namespace <<<"${OWNED_OBJECTS[index]}"
    kubectl delete "$resource" ${namespace:+--namespace "$namespace"} \
      --ignore-not-found --wait --timeout=180s
  done
  OWNED_OBJECTS=()
}

clean_up() {
  local status=$?
  set +e
  if [[ "${TRAINER_HELM_LIFECYCLE_KEEP_FIXTURES:-}" == true ]]; then
    echo "Kept for diagnosis: ${OWNED_OBJECTS[*]}"
  else
    delete_owned_objects
  fi
  rm -rf "$TEMPORARY_DIRECTORY"
  exit "$status"
}

# The name must be free, the creation must succeed, and only then is the object
# owned by this run. The exit handler that deletes is registered last.
create_owned() {
  local manifest="$1" resource="$2" namespace="${3:-}"
  if object_exists "$resource" "$namespace"; then
    fail "${resource} exists already; this run does not own it and leaves it untouched."
  fi
  kubectl create ${namespace:+--namespace "$namespace"} -f "$manifest"
  OWNED_OBJECTS+=("${resource}|${namespace}")
  trap clean_up EXIT
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

# Reads every recorded object again, which also proves that it is still readable.
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
  local manifest="$1" name="$2" runtime_kind="$3" runtime_name="$4" manager="${5:-}"
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
  if [[ -n "$manager" ]]; then
    echo "  managedBy: ${manager}" >>"$manifest"
  fi
}

# A suspended TrainJob that the Trainer controller reconciles: its runtime
# snapshot and its JobSet must appear, and the JobSet must belong to it.
create_reconciled_train_job() {
  local name="$1" runtime_kind="$2" runtime_name="$3" job_uid owner_uid
  write_train_job_manifest "${TEMPORARY_DIRECTORY}/${name}.yaml" "$name" "$runtime_kind" "$runtime_name"
  create_owned "${TEMPORARY_DIRECTORY}/${name}.yaml" "trainjob/${name}" "$TEST_NAMESPACE"
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
  create_owned "${TEMPORARY_DIRECTORY}/${ADMINISTRATOR_RUNTIME}.json" \
    "clustertrainingruntime/${ADMINISTRATOR_RUNTIME}"
  record_identity "clustertrainingruntime/${ADMINISTRATOR_RUNTIME}"
  create_owned "${TEMPORARY_DIRECTORY}/${NAMESPACED_RUNTIME}.json" \
    "trainingruntime/${NAMESPACED_RUNTIME}" "$TEST_NAMESPACE"
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

# A denial must come from the admission webhook and must name the absent runtime.
# A connection, timeout or authorization failure is no evidence of admission.
expect_admission_denial() {
  local runtime_name="$1" output="${TEMPORARY_DIRECTORY}/denial.txt"
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

# Server-side dry runs reach the admission webhooks and persist nothing.
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

# Prints present, absent or mixed for the test property of the live definition.
live_api_test_property() {
  kubectl get crd/trainjobs.trainer.kubeflow.org -o json | python3 -c '
import json
import sys

found = [
    sys.argv[1] in version["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]
    for version in json.load(sys.stdin)["spec"]["versions"]
]
print("present" if all(found) else "mixed" if any(found) else "absent")
' "$API_TEST_PROPERTY"
}

# A failed read must not pass for an answer about the property.
assert_api_test_property() {
  local expected="$1" message="$2" found
  found=$(live_api_test_property) ||
    fail "The live TrainJob definition could not be read, which is no evidence about the property ${API_TEST_PROPERTY}."
  [[ "$found" == "$expected" ]] || fail "$message"
}

definition_generation() {
  kubectl get crd/trainjobs.trainer.kubeflow.org -o jsonpath='{.metadata.generation}'
}

retire_catalog() {
  helm uninstall trainer-runtimes --namespace "$RELEASE_NAMESPACE" --wait --timeout 5m
  if object_exists "clustertrainingruntime/${CATALOG_RUNTIME}"; then
    fail "${CATALOG_RUNTIME} is still present after the catalog was uninstalled."
  fi
}

# A runtime snapshot or a JobSet would mean that a controller reconciled the held
# TrainJob. Both reads must succeed and return nothing; see object_exists.
assert_not_reconciled() {
  local job="$1" moment="$2" resource
  for resource in "configmap/${job}-runtime-snapshot" "jobset/${job}"; do
    if object_exists "$resource" "$TEST_NAMESPACE" \
      "The TrainJob ${job} may have been reconciled."; then
      fail "The TrainJob ${job} has ${resource} ${moment}: it was reconciled, so this is not the case before the first snapshot."
    fi
  done
}

# Reads at once and then every second; the last pass begins at or after the end of
# the window. A timeout of kubectl wait --for=create cannot serve here, because a
# denied or failed read ends that command exactly as the wanted timeout does.
assert_not_reconciled_throughout_the_window() {
  local job="$1" pass_started=$SECONDS deadline
  deadline=$((pass_started + SNAPSHOT_ABSENCE_SECONDS))
  while true; do
    assert_not_reconciled "$job" "within ${SNAPSHOT_ABSENCE_SECONDS} seconds of its creation"
    ((pass_started < deadline)) || break
    sleep 1
    pass_started=$SECONDS
  done
}

restore_catalog() {
  ./tests/trainer_helm_install.sh trainer-runtimes
  assert_release_deployed trainer-runtimes
  echo "${CATALOG_RUNTIME} is back with the UID $(uid "clustertrainingruntime/${CATALOG_RUNTIME}")."
}

scenario_smoke() {
  assert_admission_works
  # A completed SDK TrainJob proves admission and reconciliation together.
  ./tests/trainer_test.sh "$TEST_NAMESPACE"
  proved "smoke: admission denies an absent runtime and admits ${CATALOG_RUNTIME}; an SDK TrainJob completed."
}

scenario_fixtures() {
  ensure_fixtures
  assert_identities_retained "the creation of the fixtures"
  proved "fixtures: a namespaced TrainingRuntime and its TrainJob are admitted; both fixture TrainJobs own a runtime snapshot and a JobSet."
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
  previous_revision=$(current_revision trainer)
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
  ./tests/trainer_test.sh "$TEST_NAMESPACE"
  proved "controller-upgrade-rollback: a changed rollout and its rollback keep every recorded identity and the catalog; admission works and an SDK TrainJob completed afterwards."
}

scenario_controller_reinstall() {
  local catalog_runtime_uid webhook
  ensure_fixtures
  catalog_runtime_uid=$(uid "clustertrainingruntime/${CATALOG_RUNTIME}")
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
  ./tests/trainer_test.sh "$TEST_NAMESPACE"
  proved "controller-reinstall: the webhook configurations leave with trainer; the definitions, the catalog, the namespace and every recorded identity stay; admission works and an SDK TrainJob completed after the reinstallation."
}

scenario_api_upgrade() {
  local generation_before generation_changed api_job="${NAME_PREFIX}-api-job"
  ensure_fixtures
  assert_api_test_property absent \
    "The live TrainJob definition already has the property ${API_TEST_PROPERTY}."
  cp -R applications/trainer/helm-crds "${TEMPORARY_DIRECTORY}/apis"
  python3 - "${TEMPORARY_DIRECTORY}/apis/charts/trainer-api-payload/manifests/definitions/trainjobs.trainer.kubeflow.org.yaml" \
    "$API_TEST_PROPERTY" <<'PY'
import sys
from pathlib import Path

import yaml

path = Path(sys.argv[1])
loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
definition = yaml.load(path.read_text(), Loader=loader)
for version in definition["spec"]["versions"]:
    properties = version["schema"]["openAPIV3Schema"]["properties"]["spec"]["properties"]
    assert sys.argv[2] not in properties
    properties[sys.argv[2]] = {
        "description": "Optional property of the Trainer Helm lifecycle test.",
        "type": "string",
    }
path.write_text(yaml.dump(definition, Dumper=dumper, sort_keys=False))
PY
  generation_before=$(definition_generation)
  helm upgrade trainer-apis "${TEMPORARY_DIRECTORY}/apis" \
    --namespace "$RELEASE_NAMESPACE" --wait --timeout 5m
  assert_release_deployed trainer-apis
  wait_for_established_definitions
  assert_api_test_property present \
    "The live TrainJob definition does not serve the property ${API_TEST_PROPERTY}."
  generation_changed=$(definition_generation)
  ((generation_changed > generation_before)) ||
    fail "The generation of the TrainJob definition did not increase."
  assert_identities_retained "the changed upgrade of trainer-apis"
  create_reconciled_train_job "$api_job" ClusterTrainingRuntime "$CATALOG_RUNTIME"
  record_reconciled_train_job "$api_job"

  helm upgrade trainer-apis "$API_CHART" --namespace "$RELEASE_NAMESPACE" --wait --timeout 5m
  assert_release_deployed trainer-apis
  wait_for_established_definitions
  assert_api_test_property absent \
    "The live TrainJob definition still has the property ${API_TEST_PROPERTY}."
  assert_identities_retained "the upgrade of trainer-apis back to the unchanged chart"
  assert_admission_works
  proved "api-upgrade: trainer-apis served one more optional TrainJob property after an upgrade; TrainJobs, both runtime kinds and JobSets stayed readable with their UIDs; a new TrainJob was admitted and reconciled; the unchanged chart removed the property again."
}

scenario_api_reinstall() {
  local definition owner
  ensure_fixtures
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
  previous_revision=$(current_revision trainer-runtimes)
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

scenario_retirement_before_snapshot() {
  local unmanaged_job="${NAME_PREFIX}-unmanaged-job" unmanaged_job_uid
  # Refused before anything is created. An unreadable query is not an absent Kueue.
  if object_exists crd/workloads.kueue.x-k8s.io "" \
    "The scenario is refused: Kueue may be installed and could reconcile a TrainJob with managedBy ${EXTERNAL_MANAGER}."; then
    fail "Kueue is installed and could reconcile a TrainJob with managedBy ${EXTERNAL_MANAGER}."
  fi
  ensure_fixtures
  # Admitted while the runtime exists; the Trainer controller skips it, so it
  # has no snapshot when the runtime is retired.
  write_train_job_manifest "${TEMPORARY_DIRECTORY}/${unmanaged_job}.yaml" "$unmanaged_job" \
    ClusterTrainingRuntime "$CATALOG_RUNTIME" "$EXTERNAL_MANAGER"
  create_owned "${TEMPORARY_DIRECTORY}/${unmanaged_job}.yaml" "trainjob/${unmanaged_job}" "$TEST_NAMESPACE"
  unmanaged_job_uid=$(uid "trainjob/${unmanaged_job}" "$TEST_NAMESPACE")
  assert_not_reconciled_throughout_the_window "$unmanaged_job"

  retire_catalog
  assert_identities_retained "the uninstallation of trainer-runtimes"
  write_train_job_manifest "${TEMPORARY_DIRECTORY}/new-submission.yaml" "${NAME_PREFIX}-new-submission" \
    ClusterTrainingRuntime "$CATALOG_RUNTIME"
  expect_admission_denial "$CATALOG_RUNTIME" kubectl create --namespace "$TEST_NAMESPACE" \
    --dry-run=server -f "${TEMPORARY_DIRECTORY}/new-submission.yaml"
  expect_admission_denial "$CATALOG_RUNTIME" kubectl patch "trainjob/${unmanaged_job}" \
    --namespace "$TEST_NAMESPACE" --type merge -p '{"spec":{"suspend":false}}'
  assert_not_reconciled "$unmanaged_job" "while ${CATALOG_RUNTIME} is absent"
  assert_uid "trainjob/${unmanaged_job}" "$unmanaged_job_uid" "$TEST_NAMESPACE" "the uninstallation of trainer-runtimes"

  restore_catalog
  kubectl patch "trainjob/${unmanaged_job}" --namespace "$TEST_NAMESPACE" \
    --type merge -p '{"spec":{"suspend":false}}' --dry-run=server
  assert_uid "trainjob/${unmanaged_job}" "$unmanaged_job_uid" "$TEST_NAMESPACE" "the reinstallation of trainer-runtimes"
  assert_identities_retained "the reinstallation of trainer-runtimes"
  assert_not_reconciled "$unmanaged_job" "at the end of the scenario"
  proved "retirement-before-snapshot: a TrainJob admitted while ${CATALOG_RUNTIME} existed and held by spec.managedBy had neither a snapshot nor a JobSet in any read, and every read succeeded; admission denies its validated update and a new submission while the runtime is absent, and admits the update after the catalog returned."
}

for release in trainer-apis trainer trainer-runtimes; do
  assert_release_deployed "$release"
done
kubectl get namespace "$RELEASE_NAMESPACE"
kubectl get namespace "$TEST_NAMESPACE"

for scenario in "${SELECTED_SCENARIOS[@]}"; do
  echo "Scenario ${scenario} ..."
  "scenario_${scenario//-/_}"
done

if [[ "${TRAINER_HELM_LIFECYCLE_KEEP_FIXTURES:-}" != true ]]; then
  # The snapshots must leave with their TrainJobs, which proves their ownership.
  delete_owned_objects
  for job in "${!RECORDED_SNAPSHOT_DIGESTS[@]}"; do
    kubectl wait "configmap/${job}-runtime-snapshot" --namespace "$TEST_NAMESPACE" \
      --for=delete --timeout=180s
  done
fi
echo "PASS: ${SELECTED_SCENARIOS[*]}. Evidence: ${EVIDENCE_DIRECTORY}"
echo 'Scenarios that were not selected are not proved by this run.'
