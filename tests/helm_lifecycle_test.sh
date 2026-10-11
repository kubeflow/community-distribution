#!/usr/bin/env bash
# Helm release lifecycle of every Kubeflow chart, on one disposable cluster on
# which every Helm installer has already run.
#
#   tests/helm_lifecycle_test.sh [--smoke-only] [chart ...]
#
# Without a chart name every chart in CHART_ORDER runs, least destructive
# first. Chart names select a subset in that same order. --smoke-only runs the
# non-destructive smoke_<chart> probe of the named charts and makes no Helm
# operation.
#
# Every chart goes through the same sequence, run_release_cycle: an upgrade to
# a disposable changed chart copy observed on the live controller, a rollback
# observed the same way, an uninstall that must delete every release object
# except the ones annotated helm.sh/resource-policy: keep, and a reinstall
# through the chart's existing installer. Hooks named after the cycle hold the
# checks that are specific to one chart: the identities that must survive, a
# probe that proves recovery after the reinstall, and chart-specific
# expectations after the changed upgrade, the uninstall and the reinstall.
#
# Environment:
#   HELM_LIFECYCLE_DISPOSABLE=true   required for every non-smoke run
#   KF_PROFILE                       profile namespace, default kubeflow-user-example-com
#   HUB_REGISTRY_VALUES_FILE,
#   HUB_CATALOG_VALUES_FILE          private values of the two Hub releases (hub only)
#
# Evidence is written under logs/helm-lifecycle/<chart>/ and the workflow
# uploads it. On failure the fixtures of the failing chart stay on the cluster.
#
# To add a chart: write lifecycle_<chart> (fixtures, descriptor, run_release_cycle,
# fixture removal), its hooks, and append the chart to CHART_ORDER. Foundation
# charts go last: their uninstall removes namespaces, gateways, certificates or
# roles that every chart above them needs.
# shellcheck disable=SC2317,SC2329
set -euo pipefail

REPOSITORY_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPOSITORY_ROOT"

CHART_ORDER=(katib trainer ray spark workspaces hub kserve-ui kserve knative-serving knative-eventing)

usage() {
    echo "Usage: tests/helm_lifecycle_test.sh [--smoke-only] [chart ...]" >&2
    echo "Charts: ${CHART_ORDER[*]}" >&2
}

SMOKE_ONLY=false
REQUESTED_CHARTS=()
for argument in "$@"; do
    case "$argument" in
        --smoke-only) SMOKE_ONLY=true ;;
        -*) usage; exit 2 ;;
        *) REQUESTED_CHARTS+=("$argument") ;;
    esac
done
for requested in "${REQUESTED_CHARTS[@]}"; do
    if [[ " ${CHART_ORDER[*]} " != *" $requested "* ]]; then
        echo "Unknown chart: $requested" >&2
        usage
        exit 2
    fi
done
SELECTED_CHARTS=()
for chart in "${CHART_ORDER[@]}"; do
    if (( ${#REQUESTED_CHARTS[@]} == 0 )) || [[ " ${REQUESTED_CHARTS[*]} " == *" $chart "* ]]; then
        SELECTED_CHARTS+=("$chart")
    fi
done
if [[ "$SMOKE_ONLY" == true ]]; then
    if (( ${#REQUESTED_CHARTS[@]} == 0 )); then
        echo "--smoke-only needs the names of the charts to probe" >&2
        exit 2
    fi
elif [[ "${HELM_LIFECYCLE_DISPOSABLE:-}" != true ]]; then
    echo "Set HELM_LIFECYCLE_DISPOSABLE=true only for a disposable cluster that no other test needs" >&2
    exit 1
fi

export KF_PROFILE=${KF_PROFILE:-kubeflow-user-example-com}
EVIDENCE_ROOT=logs/helm-lifecycle
TEMPORARY_DIRECTORY=$(mktemp -d)
UPGRADE_TIMEOUT=10m
CURRENT_CHART=""
CYCLE=""
EVIDENCE_PREFIX=""
DIAGNOSTIC_NAMESPACES=()
DIAGNOSTIC_DEPLOYMENTS=()
MANIFEST_NAMESPACES=()
MANIFEST_DEPLOYMENTS=()

# One isolated Helm environment for the whole run: every chart here is a local
# directory, and the installers isolate themselves. Inherited repository and
# plugin settings of the caller never reach a Helm command.
source scripts/library.sh
require_helm_major_version 4
isolate_helm_environment "$TEMPORARY_DIRECTORY/helm"

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

announce() {
    echo "==== ${CURRENT_CHART}: $*"
}

evidence_directory() {
    local directory="$EVIDENCE_ROOT/$CURRENT_CHART${1:+/$EVIDENCE_PREFIX$1}"
    mkdir -p "$directory"
    echo "$directory"
}

evidence_file() {
    echo "$(evidence_directory)/${EVIDENCE_PREFIX}$1"
}

# Resources, events and the last log lines of the namespaces and Deployments of
# the current release, plus explicit extras. Never fails: it runs on failure too.
capture_diagnostics() {
    local directory namespace deployment
    directory=$(evidence_directory "$1") || return 0
    for namespace in "${RELEASE_NAMESPACE:-}" "$KF_PROFILE" "${MANIFEST_NAMESPACES[@]}" "${DIAGNOSTIC_NAMESPACES[@]}"; do
        [[ -n "$namespace" ]] || continue
        [[ -e "$directory/resources-$namespace.yaml" ]] && continue
        kubectl get deployments,statefulsets,pods,events -n "$namespace" --request-timeout=10s -o yaml \
            >"$directory/resources-$namespace.yaml" 2>&1 || true
    done
    for deployment in "${MANIFEST_DEPLOYMENTS[@]}" "${DIAGNOSTIC_DEPLOYMENTS[@]}"; do
        kubectl logs "deployment/${deployment#*/}" -n "${deployment%%/*}" --request-timeout=10s --tail=100 \
            >"$directory/${deployment#*/}.log" 2>&1 || true
    done
    if [[ -n "${RELEASE_NAME:-}" ]]; then
        helm history "$RELEASE_NAME" -n "$RELEASE_NAMESPACE" >"$directory/helm-history.txt" 2>&1 || true
    fi
}

finish() {
    local status=$?
    trap - EXIT
    if (( status != 0 )) && [[ -n "$CURRENT_CHART" ]]; then
        capture_diagnostics failure || true
        echo "Preserving the fixtures of $CURRENT_CHART after failure; see $EVIDENCE_ROOT/$CURRENT_CHART/" >&2
    fi
    rm -rf "$TEMPORARY_DIRECTORY" || true
    exit "$status"
}
trap finish EXIT

# The hook runs unconditionally after the existence test, so set -e applies inside it.
run_hook() {
    if declare -F "$1" >/dev/null; then
        "$1"
    fi
}

current_revision() {
    helm history "$1" -n "$2" -o json |
        python3 -c 'import json, sys; print(json.load(sys.stdin)[-1]["revision"])'
}

assert_release_deployed() {
    helm status "$1" -n "$2" -o json |
        python3 -c 'import json, sys; status = json.load(sys.stdin)["info"]["status"]; assert status == "deployed", status'
}

# Deletion assertions read with --ignore-not-found and require empty output; a
# failed read is an error, never evidence of absence.
assert_absent() {
    local found
    found=$(kubectl get "$1" ${2:+-n "$2"} --ignore-not-found -o name)
    [[ -z "$found" ]] || fail "$1 still exists${2:+ in $2}"
}

wait_for_rollouts() {
    local deployment
    for deployment in "$@"; do
        kubectl rollout status "deployment/${deployment#*/}" -n "${deployment%%/*}" --timeout=300s
    done
}

deployment_lifecycle_annotation() {
    kubectl get "deployment/$2" -n "$1" \
        -o jsonpath='{.spec.template.metadata.annotations.tests\.kubeflow\.org/lifecycle}'
}

deployment_replicas() {
    kubectl get "deployment/$2" -n "$1" -o jsonpath='{.spec.replicas}'
}

# The release manifest, as Helm stored it, is the contract of every retention
# check: objects annotated helm.sh/resource-policy: keep survive an uninstall,
# everything else must disappear. This program reads the current state of
# every manifest object (two kubectl calls: objects with an explicit namespace,
# then the rest in the release namespace) and prints one sorted line each:
#   KIND NAMESPACE NAME UID-or-ABSENT KEEP
INVENTORY_PROGRAM="$TEMPORARY_DIRECTORY/inventory.py"
cat >"$INVENTORY_PROGRAM" <<'PYTHON'
import json
import pathlib
import subprocess
import sys
import tempfile

import yaml

manifest, release_namespace = sys.argv[1:3]
documents = [
    document
    for document in yaml.safe_load_all(pathlib.Path(manifest).read_text())
    if document and document.get("kind")
]
unretained_definitions = {
    (document["spec"]["group"], document["spec"]["names"]["kind"])
    for document in documents
    if document["kind"] == "CustomResourceDefinition"
    and document["metadata"].get("annotations", {}).get("helm.sh/resource-policy") != "keep"
}


def group(document):
    return document["apiVersion"].split("/")[0] if "/" in document["apiVersion"] else ""


def keep(document):
    return document["metadata"].get("annotations", {}).get("helm.sh/resource-policy") == "keep"


expected = [
    document
    for document in documents
    if (group(document), document["kind"]) not in unretained_definitions
]


def read(subset, namespace_arguments):
    if not subset:
        return []
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
        yaml.safe_dump_all(subset, handle)
    result = subprocess.run(
        ["kubectl", "get", "-f", handle.name, *namespace_arguments, "--ignore-not-found", "-o", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    if not result.stdout.strip():
        return []
    loaded = json.loads(result.stdout)
    return loaded["items"] if loaded.get("kind") == "List" else [loaded]


explicit = [document for document in expected if document["metadata"].get("namespace")]
implicit = [document for document in expected if not document["metadata"].get("namespace")]
# Some upstream charts render a namespace on cluster-scoped objects, and a
# namespaced object without a namespace lands in the release namespace, so a
# manifest object is matched by kind and name within those candidate namespaces.
found = {}
for item in read(explicit, []) + read(implicit, ["-n", release_namespace]):
    found.setdefault((item["kind"], item["metadata"]["name"]), {})[item["metadata"].get("namespace", "")] = item["metadata"]["uid"]
lines = []
for document in expected:
    kind, name = document["kind"], document["metadata"]["name"]
    namespace = document["metadata"].get("namespace", "")
    candidates = found.get((kind, name), {})
    uid = None
    for candidate in (namespace, release_namespace, ""):
        if candidate in candidates:
            namespace, uid = candidate, candidates[candidate]
            break
    lines.append(f"{kind} {namespace or '-'} {name} {uid or 'ABSENT'} {int(keep(document))}")
print("\n".join(sorted(lines)))
PYTHON

# Rendered manifests contain Secret data (the Hub private values), so they stay
# in the temporary directory; only object inventories go into the evidence.
manifest_path() {
    echo "$TEMPORARY_DIRECTORY/$CYCLE-manifest-$1.yaml"
}

release_inventory() {
    python3 "$INVENTORY_PROGRAM" "$(manifest_path before)" "$RELEASE_NAMESPACE"
}

assert_release_objects_retained() {
    local label="$1" after
    after=$(evidence_file "release-objects-$label.txt")
    release_inventory >"$after"
    diff -u "$(evidence_file release-objects-before.txt)" "$after" ||
        fail "release objects changed identity after $label"
}

# After an uninstall the kept objects keep their UID and every other object is gone.
assert_release_objects_removed() {
    local after
    after=$(evidence_file release-objects-after-uninstall.txt)
    release_inventory >"$after"
    diff -u <(grep ' 1$' "$(evidence_file release-objects-before.txt)") <(grep ' 1$' "$after") ||
        fail "kept objects changed identity across the uninstall"
    if grep ' 0$' "$after" | grep -v ' ABSENT 0$'; then
        fail "release objects survived the uninstall"
    fi
}

# Kept objects must still carry their original UID after the reinstall.
assert_kept_objects_retained() {
    local after
    after=$(evidence_file release-objects-after-reinstall.txt)
    release_inventory >"$after"
    diff -u <(grep ' 1$' "$(evidence_file release-objects-before.txt)") <(grep ' 1$' "$after") ||
        fail "kept objects changed identity across the reinstall"
}

# A disposable chart copy whose named Deployments carry a changed Pod-template
# annotation. The committed payload never changes.
write_changed_chart() {
    local chart="$1" candidate="$TEMPORARY_DIRECTORY/$CYCLE-changed" evidence
    shift
    evidence=$(evidence_directory changed-candidate)
    rm -rf "$candidate"
    cp -a "$chart" "$candidate"
    python3 - "$candidate" "$evidence" "$@" <<'PYTHON'
import pathlib
import shutil
import sys

import yaml

candidate, evidence = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
wanted = {name.split("/")[-1] for name in sys.argv[3:]}
changed = set()
for path in sorted(candidate.rglob("*.yaml")):
    if "manifests" not in path.parts or "kind: Deployment" not in path.read_text():
        continue
    documents = list(yaml.safe_load_all(path.read_text()))
    hit = False
    for document in documents:
        if document and document.get("kind") == "Deployment" and document["metadata"]["name"] in wanted:
            document["spec"]["template"]["metadata"].setdefault("annotations", {})["tests.kubeflow.org/lifecycle"] = "changed"
            changed.add(document["metadata"]["name"])
            hit = True
    if hit:
        path.write_text(yaml.safe_dump_all(documents, sort_keys=False, explicit_start=True))
        shutil.copy2(path, evidence / path.name)
missing = wanted - changed
assert not missing, f"Deployments not found in the chart payload: {sorted(missing)}"
PYTHON
    echo "$candidate"
}

snapshot_identities() {
    "identities_$CYCLE" >"$(evidence_file "identities-$1.txt")"
}

assert_identities_retained() {
    snapshot_identities "$1"
    diff -u "$(evidence_file identities-before.txt)" "$(evidence_file "identities-$1.txt")" ||
        fail "retained identities changed after $1"
}

assert_release_identities_retained() {
    declare -F "release_identities_$CYCLE" >/dev/null || return 0
    "release_identities_$CYCLE" >"$(evidence_file "release-identities-$1.txt")"
    diff -u "$(evidence_file release-identities-before.txt)" "$(evidence_file "release-identities-$1.txt")" ||
        fail "release-owned data changed after $1"
}

assert_live_change() {
    local deployment marker
    for deployment in "${CHANGED_DEPLOYMENTS[@]}"; do
        if [[ "$CHANGE_KIND" == set ]]; then
            marker=$(deployment_replicas "${deployment%%/*}" "${deployment#*/}")
            [[ "$marker" == 2 ]] || fail "$deployment has $marker replicas after the changed upgrade, expected 2"
        else
            marker=$(deployment_lifecycle_annotation "${deployment%%/*}" "${deployment#*/}")
            [[ "$marker" == changed ]] || fail "the changed upgrade did not reach the live Pod template of $deployment"
        fi
    done
}

assert_live_restoration() {
    local deployment marker
    for deployment in "${CHANGED_DEPLOYMENTS[@]}"; do
        if [[ "$CHANGE_KIND" == set ]]; then
            marker=$(deployment_replicas "${deployment%%/*}" "${deployment#*/}")
            [[ "$marker" == 1 ]] || fail "$deployment has $marker replicas after the rollback, expected 1"
        else
            marker=$(deployment_lifecycle_annotation "${deployment%%/*}" "${deployment#*/}")
            [[ -z "$marker" ]] || fail "the rollback did not restore the live Pod template of $deployment"
        fi
    done
}

reset_cycle_descriptor() {
    RELEASE_NAME=""
    RELEASE_NAMESPACE=""
    CHART_DIRECTORY=""
    UPGRADE_ARGUMENTS=()
    CHANGE_KIND=annotation
    CHANGED_DEPLOYMENTS=()
    CHANGED_SET_KEY=""
    REINSTALL_COMMAND=()
    EVIDENCE_PREFIX=""
    MANIFEST_NAMESPACES=()
    MANIFEST_DEPLOYMENTS=()
}

# The shared sequence. The chart function fills the descriptor variables above
# and defines identities_<cycle>; the other hooks are optional.
run_release_cycle() {
    CYCLE="$1"
    local rollback_revision candidate

    announce "$CYCLE: preflight"
    assert_release_deployed "$RELEASE_NAME" "$RELEASE_NAMESPACE"
    helm get manifest "$RELEASE_NAME" -n "$RELEASE_NAMESPACE" >"$(manifest_path before)"
    release_inventory >"$(evidence_file release-objects-before.txt)"
    mapfile -t MANIFEST_DEPLOYMENTS < <(awk '$1 == "Deployment" {print $2 "/" $3}' "$(evidence_file release-objects-before.txt)")
    mapfile -t MANIFEST_NAMESPACES < <(awk '$2 != "-" {print $2}' "$(evidence_file release-objects-before.txt)" | sort -u)
    if grep -q ' ABSENT ' "$(evidence_file release-objects-before.txt)"; then
        grep ' ABSENT ' "$(evidence_file release-objects-before.txt)"
        fail "release objects are missing before any operation"
    fi
    snapshot_identities before
    if declare -F "release_identities_$CYCLE" >/dev/null; then
        "release_identities_$CYCLE" >"$(evidence_file release-identities-before.txt)"
    fi

    rollback_revision=$(current_revision "$RELEASE_NAME" "$RELEASE_NAMESPACE")

    announce "$CYCLE: changed upgrade"
    capture_diagnostics before-changed-upgrade
    if [[ "$CHANGE_KIND" == set ]]; then
        helm upgrade "$RELEASE_NAME" "$CHART_DIRECTORY" -n "$RELEASE_NAMESPACE" "${UPGRADE_ARGUMENTS[@]}" \
            --set "$CHANGED_SET_KEY=2" --wait --timeout "$UPGRADE_TIMEOUT"
    else
        candidate=$(write_changed_chart "$CHART_DIRECTORY" "${CHANGED_DEPLOYMENTS[@]}")
        helm upgrade "$RELEASE_NAME" "$candidate" -n "$RELEASE_NAMESPACE" "${UPGRADE_ARGUMENTS[@]}" \
            --wait --timeout "$UPGRADE_TIMEOUT"
    fi
    wait_for_rollouts "${MANIFEST_DEPLOYMENTS[@]}"
    assert_live_change
    assert_release_objects_retained after-changed-upgrade
    assert_identities_retained after-changed-upgrade
    assert_release_identities_retained after-changed-upgrade
    run_hook "after_changed_upgrade_$CYCLE"

    announce "$CYCLE: rollback to revision $rollback_revision"
    capture_diagnostics before-rollback
    helm rollback "$RELEASE_NAME" "$rollback_revision" -n "$RELEASE_NAMESPACE" --wait --timeout "$UPGRADE_TIMEOUT"
    wait_for_rollouts "${MANIFEST_DEPLOYMENTS[@]}"
    assert_live_restoration
    assert_release_objects_retained after-rollback
    assert_identities_retained after-rollback
    assert_release_identities_retained after-rollback

    announce "$CYCLE: uninstall"
    capture_diagnostics before-uninstall
    helm uninstall "$RELEASE_NAME" -n "$RELEASE_NAMESPACE" --wait --timeout "$UPGRADE_TIMEOUT"
    assert_release_objects_removed
    assert_identities_retained after-uninstall
    run_hook "after_uninstall_$CYCLE"

    announce "$CYCLE: reinstall with ${REINSTALL_COMMAND[*]}"
    "${REINSTALL_COMMAND[@]}"
    assert_release_deployed "$RELEASE_NAME" "$RELEASE_NAMESPACE"
    assert_kept_objects_retained
    assert_identities_retained after-reinstall
    capture_diagnostics after-reinstall
    run_hook "after_reinstall_$CYCLE"
    run_hook "probe_$CYCLE"
    echo "$CYCLE: live changed upgrade and rollback, uninstall retention and reinstall recovery passed."
}

# ---------------------------------------------------------------------------
# katib: release katib in kubeflow; fixture is the grid Experiment of katib_test.sh
# ---------------------------------------------------------------------------

lifecycle_katib() {
    RELEASE_NAME=katib
    RELEASE_NAMESPACE=kubeflow
    CHART_DIRECTORY=applications/katib/helm
    UPGRADE_ARGUMENTS=(--values applications/katib/helm/ci/values-platform.yaml)
    CHANGED_DEPLOYMENTS=(kubeflow/katib-controller)
    REINSTALL_COMMAND=(./tests/katib_helm_install.sh)
    run_release_cycle katib
}

identities_katib() {
    kubectl get namespace kubeflow "$KF_PROFILE" -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.uid}{"\n"}{end}'
    kubectl get experiments.kubeflow.org,trials.kubeflow.org -n "$KF_PROFILE" -o json | python3 -c '
import json, sys
resources = json.load(sys.stdin)["items"]
experiment = next(item for item in resources if item["kind"] == "Experiment" and item["metadata"]["name"] == "grid")
trials = [item for item in resources if item["kind"] == "Trial" and any(owner["uid"] == experiment["metadata"]["uid"] for owner in item["metadata"].get("ownerReferences", []))]
assert trials, "Run katib_test.sh before the lifecycle test"
for item in sorted([experiment, *trials], key=lambda item: item["metadata"]["name"]):
    print(item["kind"], item["metadata"]["name"], item["metadata"]["uid"])
'
}

# The database storage leaves with the release (generic removal check) and
# comes back with the reinstall.
after_reinstall_katib() {
    wait_for_rollouts kubeflow/katib-controller kubeflow/katib-db-manager kubeflow/katib-mysql kubeflow/katib-ui
    kubectl get pvc/katib-mysql secret/katib-mysql-secrets -n kubeflow >/dev/null
}

# ---------------------------------------------------------------------------
# trainer: release trainer in kubeflow-system; trainer-apis and trainer-runtimes stay
# ---------------------------------------------------------------------------

TRAINER_FIXTURE=helm-lifecycle-torch
TRAINER_CATALOG_RUNTIME=torch-distributed

write_train_job_manifest() {
    cat >"$1" <<EOF
apiVersion: trainer.kubeflow.org/v1alpha1
kind: TrainJob
metadata:
  name: $2
spec:
  suspend: true
  runtimeRef:
    apiGroup: trainer.kubeflow.org
    kind: ClusterTrainingRuntime
    name: $3
  trainer:
    numNodes: 1
    command: ["python", "-c", "print('trainer lifecycle fixture')"]
EOF
}

lifecycle_trainer() {
    local job_uid owner_uid
    write_train_job_manifest "$TEMPORARY_DIRECTORY/train-job.yaml" "$TRAINER_FIXTURE" "$TRAINER_CATALOG_RUNTIME"
    kubectl create -n "$KF_PROFILE" -f "$TEMPORARY_DIRECTORY/train-job.yaml"
    kubectl wait -n "$KF_PROFILE" --for=create "configmap/$TRAINER_FIXTURE-runtime-snapshot" --timeout=180s
    kubectl wait -n "$KF_PROFILE" --for=create "jobset/$TRAINER_FIXTURE" --timeout=180s
    job_uid=$(kubectl get "trainjob/$TRAINER_FIXTURE" -n "$KF_PROFILE" -o jsonpath='{.metadata.uid}')
    owner_uid=$(kubectl get "jobset/$TRAINER_FIXTURE" -n "$KF_PROFILE" -o jsonpath='{.metadata.ownerReferences[0].uid}')
    [[ -n "$job_uid" && "$owner_uid" == "$job_uid" ]] || fail "the JobSet is not owned by the TrainJob fixture"

    RELEASE_NAME=trainer
    RELEASE_NAMESPACE=kubeflow-system
    CHART_DIRECTORY=applications/trainer/helm
    CHANGED_DEPLOYMENTS=(kubeflow-system/kubeflow-trainer-controller-manager kubeflow-system/jobset-controller-manager)
    REINSTALL_COMMAND=(./tests/trainer_helm_install.sh trainer)
    run_release_cycle trainer

    kubectl delete "trainjob/$TRAINER_FIXTURE" -n "$KF_PROFILE" --wait=true --timeout=120s
}

identities_trainer() {
    kubectl get namespace kubeflow-system -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
    kubectl get crd clustertrainingruntimes.trainer.kubeflow.org trainingruntimes.trainer.kubeflow.org \
        trainjobs.trainer.kubeflow.org jobsets.jobset.x-k8s.io \
        -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.uid}{"\n"}{end}'
    kubectl get "clustertrainingruntime/$TRAINER_CATALOG_RUNTIME" -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
    kubectl get "trainjob/$TRAINER_FIXTURE" "configmap/$TRAINER_FIXTURE-runtime-snapshot" "jobset/$TRAINER_FIXTURE" \
        -n "$KF_PROFILE" -o jsonpath='{range .items[*]}{.kind}{" "}{.metadata.name}{" "}{.metadata.uid}{"\n"}{end}'
    local digest
    digest=$(kubectl get "configmap/$TRAINER_FIXTURE-runtime-snapshot" -n "$KF_PROFILE" -o jsonpath='{.data.runtime}' | sha256sum | cut -d ' ' -f 1)
    echo "snapshot $digest"
}

after_uninstall_trainer() {
    assert_release_deployed trainer-apis kubeflow-system
    assert_release_deployed trainer-runtimes kubeflow-system
}

# A server dry run against an absent runtime must be denied by the admission
# webhook naming that runtime; one against the catalog runtime must be admitted.
probe_trainer() {
    local absent_runtime=helm-lifecycle-absent-runtime output
    output=$(evidence_file admission-denial.txt)
    write_train_job_manifest "$TEMPORARY_DIRECTORY/probe-absent.yaml" helm-lifecycle-probe "$absent_runtime"
    if kubectl create -n "$KF_PROFILE" --dry-run=server -f "$TEMPORARY_DIRECTORY/probe-absent.yaml" >"$output" 2>&1; then
        cat "$output"
        fail "admitted a TrainJob although the runtime $absent_runtime is absent"
    fi
    grep -Eiq 'admission webhook.*denied|denied the request' "$output" || fail "the failure is not an admission denial"
    grep -Fq "$absent_runtime" "$output" || fail "the admission denial does not name the runtime"
    write_train_job_manifest "$TEMPORARY_DIRECTORY/probe-present.yaml" helm-lifecycle-probe "$TRAINER_CATALOG_RUNTIME"
    kubectl create -n "$KF_PROFILE" --dry-run=server -f "$TEMPORARY_DIRECTORY/probe-present.yaml" >/dev/null
}

# ---------------------------------------------------------------------------
# ray: release kuberay-operator in kubeflow; wrapper chart around upstream KubeRay
# ---------------------------------------------------------------------------

RAY_FIXTURE=helm-lifecycle-held

lifecycle_ray() {
    local chart="$TEMPORARY_DIRECTORY/ray-chart" found
    # The upstream dependency is never committed; build it in the disposable copy.
    cp -R experimental/ray/kuberay-operator/helm "$chart"
    helm repo add kuberay https://ray-project.github.io/kuberay-helm/
    helm dependency build "$chart"

    found=$(kubectl get rayjob "$RAY_FIXTURE" -n "$KF_PROFILE" --ignore-not-found -o name)
    [[ -z "$found" ]] || fail "refusing to replace the existing fixture $found"
    python3 - experimental/ray/raycluster_example.yaml >"$TEMPORARY_DIRECTORY/ray-job.yaml" <<'PYTHON'
import sys

import yaml

cluster = next(item for item in yaml.safe_load_all(open(sys.argv[1])) if item["kind"] == "RayCluster")
yaml.safe_dump({
    "apiVersion": "ray.io/v1",
    "kind": "RayJob",
    "metadata": {"name": "helm-lifecycle-held"},
    "spec": {
        "suspend": True,
        "shutdownAfterJobFinishes": True,
        "entrypoint": "python -c 'print(42)'",
        "rayClusterSpec": cluster["spec"],
    },
}, sys.stdout)
PYTHON
    kubectl create -n "$KF_PROFILE" -f "$TEMPORARY_DIRECTORY/ray-job.yaml"
    # KubeRay checks suspend before creating the RayCluster: this fixture
    # measures retention, not work.
    kubectl wait -n "$KF_PROFILE" --for=jsonpath='{.status.jobDeploymentStatus}'=Suspended \
        "rayjob/$RAY_FIXTURE" --timeout=120s

    RELEASE_NAME=kuberay-operator
    RELEASE_NAMESPACE=kubeflow
    CHART_DIRECTORY="$chart"
    CHANGE_KIND="set"
    CHANGED_SET_KEY=kuberay-operator.replicas
    CHANGED_DEPLOYMENTS=(kubeflow/kuberay-operator)
    REINSTALL_COMMAND=(env RAY_CRDS_MANAGED_EXTERNALLY=true ./tests/ray_helm_install.sh)

    # The documented same-version schema maintenance path must not change any identity.
    identities_ray >"$TEMPORARY_DIRECTORY/ray-before-schema-maintenance.txt"
    helm show crds "$chart" >"$TEMPORARY_DIRECTORY/ray-definitions.yaml"
    kubectl apply --server-side --field-manager=kubeflow-crd-maintenance -f "$TEMPORARY_DIRECTORY/ray-definitions.yaml"
    identities_ray >"$TEMPORARY_DIRECTORY/ray-after-schema-maintenance.txt"
    diff -u "$TEMPORARY_DIRECTORY/ray-before-schema-maintenance.txt" "$TEMPORARY_DIRECTORY/ray-after-schema-maintenance.txt" ||
        fail "the schema maintenance apply changed an identity"

    run_release_cycle ray

    kubectl delete -n "$KF_PROFILE" -f "$TEMPORARY_DIRECTORY/ray-job.yaml" --wait=true --timeout=120s
}

identities_ray() {
    kubectl get crd rayclusters.ray.io rayjobs.ray.io rayservices.ray.io raycronjobs.ray.io -o json | python3 -c '
import hashlib, json, sys
for item in sorted(json.load(sys.stdin)["items"], key=lambda item: item["metadata"]["name"]):
    digest = hashlib.sha256(json.dumps(item["spec"], sort_keys=True).encode()).hexdigest()
    print(item["metadata"]["name"], item["metadata"]["uid"], digest)
'
    kubectl get rayjob "$RAY_FIXTURE" -n "$KF_PROFILE" -o json | python3 -c '
import hashlib, json, sys
item = json.load(sys.stdin)
print("rayjob", item["metadata"]["uid"], hashlib.sha256(json.dumps(item["spec"], sort_keys=True).encode()).hexdigest())
'
    kubectl get namespace kubeflow "$KF_PROFILE" -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.uid}{"\n"}{end}'
}

# ---------------------------------------------------------------------------
# spark: release spark-operator in kubeflow; wrapper chart around the upstream operator
# ---------------------------------------------------------------------------

SPARK_RETAINED_APPLICATION=spark-pi-python
SPARK_NEW_APPLICATION=reinstallation-spark-pi

wait_for_spark_application() {
    local application="$1" state=""
    for _ in $(seq 1 120); do
        state=$(kubectl get sparkapplication "$application" -n "$KF_PROFILE" -o jsonpath='{.status.applicationState.state}')
        [[ "$state" == COMPLETED ]] && return 0
        [[ "$state" == FAILED ]] && break
        sleep 5
    done
    kubectl describe sparkapplication "$application" -n "$KF_PROFILE" >&2 || true
    fail "SparkApplication $application is ${state:-without a state}, expected COMPLETED"
}

lifecycle_spark() {
    local chart="$TEMPORARY_DIRECTORY/spark-chart" found
    cp -R applications/spark/spark-operator/helm "$chart"
    helm repo add spark-operator https://kubeflow.github.io/spark-operator
    helm dependency build "$chart"

    found=$(kubectl get sparkapplication "$SPARK_RETAINED_APPLICATION" "$SPARK_NEW_APPLICATION" -n "$KF_PROFILE" --ignore-not-found -o name)
    [[ -z "$found" ]] || fail "refusing to replace the existing fixtures $found"
    kubectl label namespace "$KF_PROFILE" istio-injection=enabled --overwrite
    # A user application that the operator has reconciled to completion.
    kubectl create -n "$KF_PROFILE" -f applications/spark/sparkapplication_example.yaml
    wait_for_spark_application "$SPARK_RETAINED_APPLICATION"

    RELEASE_NAME=spark-operator
    RELEASE_NAMESPACE=kubeflow
    CHART_DIRECTORY="$chart"
    UPGRADE_ARGUMENTS=(--values "$chart/ci/values-kubeflow.yaml")
    CHANGE_KIND="set"
    CHANGED_SET_KEY=spark-operator.controller.replicas
    CHANGED_DEPLOYMENTS=(kubeflow/spark-operator-controller)
    REINSTALL_COMMAND=(./tests/spark_helm_install.sh)
    run_release_cycle spark

    kubectl delete sparkapplication "$SPARK_RETAINED_APPLICATION" "$SPARK_NEW_APPLICATION" -n "$KF_PROFILE" --ignore-not-found
}

identities_spark() {
    kubectl get crd scheduledsparkapplications.sparkoperator.k8s.io sparkapplications.sparkoperator.k8s.io \
        sparkconnects.sparkoperator.k8s.io -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.uid}{"\n"}{end}'
    kubectl get sparkapplication "$SPARK_RETAINED_APPLICATION" -n "$KF_PROFILE" \
        -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{" "}{.status.applicationState.state}{" "}{.status.submissionID}{"\n"}'
    kubectl get namespace kubeflow "$KF_PROFILE" -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.uid}{"\n"}{end}'
}

# The recovered operator reconciles new work.
after_reinstall_spark() {
    sed "s/^  name: ${SPARK_RETAINED_APPLICATION}\$/  name: ${SPARK_NEW_APPLICATION}/" \
        applications/spark/sparkapplication_example.yaml | kubectl create -n "$KF_PROFILE" -f -
    wait_for_spark_application "$SPARK_NEW_APPLICATION"
}

# ---------------------------------------------------------------------------
# workspaces: release kubeflow-workspaces in kubeflow; the chart owns namespace kubeflow-workspaces
# ---------------------------------------------------------------------------

WORKSPACES_FIXTURE=helm-lifecycle-retained
WORKSPACES_CLAIM=helm-lifecycle-home
WORKSPACES_KIND_CREATED=false

lifecycle_workspaces() {
    local found
    found=$(kubectl get workspacekind jupyterlab --ignore-not-found -o name)
    if [[ -z "$found" ]]; then
        kubectl apply -f tests/workspacekind.test.yaml
        WORKSPACES_KIND_CREATED=true
    fi
    # A paused Workspace needs no Pod and no image; it measures retention.
    kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $WORKSPACES_CLAIM
  namespace: $KF_PROFILE
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
---
apiVersion: kubeflow.org/v1beta1
kind: Workspace
metadata:
  name: $WORKSPACES_FIXTURE
  namespace: $KF_PROFILE
spec:
  paused: true
  kind: jupyterlab
  podTemplate:
    volumes:
      home: $WORKSPACES_CLAIM
    options:
      imageConfig: "jupyter-scipy:v1.10.0"
      podConfig: "tiny_cpu"
EOF
    kubectl wait --for=jsonpath='{.status.state}'=Paused "workspace/$WORKSPACES_FIXTURE" -n "$KF_PROFILE" --timeout=300s

    RELEASE_NAME=kubeflow-workspaces
    RELEASE_NAMESPACE=kubeflow
    CHART_DIRECTORY=applications/workspaces/helm
    UPGRADE_ARGUMENTS=(--values applications/workspaces/helm/ci/values-istio.yaml)
    CHANGED_DEPLOYMENTS=(kubeflow-workspaces/workspaces-controller)
    REINSTALL_COMMAND=(./tests/workspaces_helm_install.sh)
    run_release_cycle workspaces

    kubectl delete "workspace/$WORKSPACES_FIXTURE" "pvc/$WORKSPACES_CLAIM" -n "$KF_PROFILE" --ignore-not-found
    if [[ "$WORKSPACES_KIND_CREATED" == true ]]; then
        kubectl delete workspacekind jupyterlab --ignore-not-found
    fi
}

identities_workspaces() {
    kubectl get crd workspacekinds.kubeflow.org workspaces.kubeflow.org \
        -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.uid}{"\n"}{end}'
    kubectl get workspacekind jupyterlab -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
    kubectl get "workspace/$WORKSPACES_FIXTURE" "pvc/$WORKSPACES_CLAIM" -n "$KF_PROFILE" \
        -o jsonpath='{range .items[*]}{.kind}{" "}{.metadata.name}{" "}{.metadata.uid}{"\n"}{end}'
}

# The validating webhook works again and the aggregated roles keep their rules.
probe_workspaces() {
    local output deadline role
    kubectl wait --for=condition=Ready certificate/workspaces-serving-cert -n kubeflow-workspaces --timeout=300s
    kubectl wait --for='jsonpath={.webhooks[0].clientConfig.caBundle}' \
        validatingwebhookconfiguration/workspaces-validating-webhook-configuration --timeout=300s
    kubectl wait --for='jsonpath={.subsets[0].addresses[0].ip}' endpoints/workspaces-webhook-service \
        -n kubeflow-workspaces --timeout=300s
    # A Workspace naming an absent kind passes the schema; only the webhook rejects it.
    output=$(evidence_file invalid-workspace-rejection.txt)
    deadline=$((SECONDS + 300))
    while true; do
        if kubectl apply -f - >"$output" 2>&1 <<EOF
apiVersion: kubeflow.org/v1beta1
kind: Workspace
metadata:
  name: helm-lifecycle-invalid
  namespace: $KF_PROFILE
spec:
  paused: true
  kind: helm-lifecycle-kind-that-does-not-exist
  podTemplate:
    volumes:
      home: helm-lifecycle-invalid-home
    options:
      imageConfig: "jupyter-scipy:v1.10.0"
      podConfig: "tiny_cpu"
EOF
        then
            kubectl delete workspace helm-lifecycle-invalid -n "$KF_PROFILE" --wait=false || true
            fail "the invalid Workspace was admitted"
        fi
        grep -qF 'workspace kind "helm-lifecycle-kind-that-does-not-exist" not found' "$output" && break
        (( SECONDS < deadline )) || fail "the validating webhook did not reject the invalid Workspace"
        sleep 5
    done
    # The aggregation controller, not Helm, owns the rules of the aggregated roles.
    for role in kubeflow-workspaces-admin kubeflow-workspaces-edit kubeflow-workspaces-view; do
        kubectl get clusterrole "$role" --show-managed-fields -o json | python3 -c '
import json, sys
role = json.load(sys.stdin)
assert role.get("rules"), "aggregated role has no rules"
managers = [entry["manager"] for entry in role["metadata"].get("managedFields", []) if "f:rules" in entry.get("fieldsV1", {})]
assert "helm" not in managers, managers
'
    done
}

# ---------------------------------------------------------------------------
# hub: releases hub-model-registry (profile namespace) and hub-model-catalog (kubeflow)
# ---------------------------------------------------------------------------

HUB_REGISTRY_NAMESPACE=kubeflow-user-example-com

registry_sql() {
    # Variables expand inside the database container, not on this host.
    # shellcheck disable=SC2016
    kubectl exec -n "$HUB_REGISTRY_NAMESPACE" deployment/model-registry-db -c db-container -- \
        sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"' sh "$1"
}

catalog_sql() {
    # Variables expand inside the database container, not on this host.
    # shellcheck disable=SC2016
    kubectl exec -n kubeflow statefulset/model-catalog-postgres -c postgres -- \
        sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -Atc "$1"' sh "$1"
}

secret_digest() {
    kubectl get secret "$2" -n "$1" -o json | python3 -c \
        'import hashlib, json, sys; print(hashlib.sha256(json.dumps(json.load(sys.stdin)["data"], sort_keys=True).encode()).hexdigest())'
}

lifecycle_hub() {
    : "${HUB_REGISTRY_VALUES_FILE:?Supply the registry private values file}"
    : "${HUB_CATALOG_VALUES_FILE:?Supply the catalog private values file}"
    local sentinel
    registry_sql "CREATE TABLE IF NOT EXISTS helm_lifecycle_probe (value text PRIMARY KEY); INSERT INTO helm_lifecycle_probe VALUES ('survives') ON CONFLICT DO NOTHING;"
    catalog_sql "CREATE TABLE IF NOT EXISTS helm_lifecycle_probe (value text PRIMARY KEY); INSERT INTO helm_lifecycle_probe VALUES ('survives') ON CONFLICT DO NOTHING;"
    sentinel=$(registry_sql "SELECT value FROM helm_lifecycle_probe")
    [[ "$sentinel" == survives ]] || fail "the registry sentinel reads '$sentinel'"
    sentinel=$(catalog_sql "SELECT value FROM helm_lifecycle_probe")
    [[ "$sentinel" == survives ]] || fail "the catalog sentinel reads '$sentinel'"

    RELEASE_NAME=hub-model-registry
    RELEASE_NAMESPACE="$HUB_REGISTRY_NAMESPACE"
    CHART_DIRECTORY=applications/hub/helm
    UPGRADE_ARGUMENTS=(--values "$HUB_REGISTRY_VALUES_FILE")
    CHANGED_DEPLOYMENTS=("$HUB_REGISTRY_NAMESPACE/model-registry-ui")
    REINSTALL_COMMAND=(./tests/hub_helm_install.sh registry "$HUB_REGISTRY_VALUES_FILE")
    EVIDENCE_PREFIX=registry-
    run_release_cycle hub_registry

    reset_cycle_descriptor
    RELEASE_NAME=hub-model-catalog
    RELEASE_NAMESPACE=kubeflow
    CHART_DIRECTORY=applications/hub/helm-catalog
    UPGRADE_ARGUMENTS=(--values "$HUB_CATALOG_VALUES_FILE")
    CHANGED_DEPLOYMENTS=(kubeflow/model-catalog-server)
    REINSTALL_COMMAND=(./tests/hub_helm_install.sh catalog "$HUB_CATALOG_VALUES_FILE")
    EVIDENCE_PREFIX=catalog-
    run_release_cycle hub_catalog
}

# The other release and both namespaces survive every registry operation.
identities_hub_registry() {
    local sentinel digest
    kubectl get namespace kubeflow "$HUB_REGISTRY_NAMESPACE" -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.uid}{"\n"}{end}'
    kubectl get deployment model-catalog-server -n kubeflow -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
    sentinel=$(catalog_sql "SELECT value FROM helm_lifecycle_probe")
    digest=$(secret_digest kubeflow model-catalog-postgres)
    echo "catalog-sentinel $sentinel"
    echo "catalog-secret $digest"
}

# Registry credentials, data and storage survive upgrades and the rollback.
release_identities_hub_registry() {
    local sentinel digest
    digest=$(secret_digest "$HUB_REGISTRY_NAMESPACE" model-registry-db-secrets)
    sentinel=$(registry_sql "SELECT value FROM helm_lifecycle_probe")
    echo "registry-secret $digest"
    echo "registry-sentinel $sentinel"
    kubectl get pvc metadata-postgres -n "$HUB_REGISTRY_NAMESPACE" -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
}

# The chart contract: the registry database storage leaves with the release.
after_uninstall_hub_registry() {
    assert_absent pvc/metadata-postgres "$HUB_REGISTRY_NAMESPACE"
}

# A fresh database: the table does not exist, so CREATE TABLE without IF NOT EXISTS proves it.
after_reinstall_hub_registry() {
    registry_sql "CREATE TABLE helm_lifecycle_probe (value text PRIMARY KEY); INSERT INTO helm_lifecycle_probe VALUES ('other-release-survives');"
}

identities_hub_catalog() {
    local sentinel
    kubectl get namespace kubeflow "$HUB_REGISTRY_NAMESPACE" -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.uid}{"\n"}{end}'
    kubectl get deployment model-registry-deployment -n "$HUB_REGISTRY_NAMESPACE" -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
    sentinel=$(registry_sql "SELECT value FROM helm_lifecycle_probe")
    [[ "$sentinel" == other-release-survives ]] || fail "the registry sentinel reads '$sentinel'"
    echo "registry-sentinel $sentinel"
    kubectl get pvc metadata-postgres -n "$HUB_REGISTRY_NAMESPACE" -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
}

release_identities_hub_catalog() {
    local sentinel digest
    digest=$(secret_digest kubeflow model-catalog-postgres)
    sentinel=$(catalog_sql "SELECT value FROM helm_lifecycle_probe")
    echo "catalog-secret $digest"
    echo "catalog-sentinel $sentinel"
}

# ---------------------------------------------------------------------------
# kserve-ui and kserve: one Ready InferenceService fixture shared by both cycles
# ---------------------------------------------------------------------------

KSERVE_FIXTURE=helm-lifecycle-sklearn
KSERVE_UI_BASE_URL=localhost:8080/kserve-endpoints

ensure_gateway_port_forward() {
    curl -s -o /dev/null --max-time 5 "http://localhost:8080/" || ./tests/port_forward_gateway.sh
}

create_inference_service() {
    kubectl apply -f - <<EOF
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: $1
  namespace: $KF_PROFILE
spec:
  predictor:
    sklearn:
      storageUri: "gs://kfserving-examples/models/sklearn/1.0/model"
      resources:
        requests:
          cpu: "50m"
          memory: "128Mi"
        limits:
          cpu: "100m"
          memory: "256Mi"
EOF
    kubectl wait --for=condition=Ready "inferenceservice/$1" -n "$KF_PROFILE" --timeout=300s
}

ensure_inference_service_fixture() {
    local found
    found=$(kubectl get inferenceservice "$KSERVE_FIXTURE" -n "$KF_PROFILE" --ignore-not-found -o name)
    [[ -n "$found" ]] || create_inference_service "$KSERVE_FIXTURE"
}

# The Models UI lists the fixture for an authorized token; a fresh cookie each time.
models_ui_lists_fixture() {
    local token cookies xsrf response
    ensure_gateway_port_forward
    token=$(kubectl -n "$KF_PROFILE" create token default-editor)
    cookies="$TEMPORARY_DIRECTORY/kserve-ui-cookies.txt"
    rm -f "$cookies"
    curl -sS --fail-with-body --retry 12 --retry-delay 2 --retry-all-errors --max-time 10 --retry-max-time 60 \
        "http://$KSERVE_UI_BASE_URL/" -H "Authorization: Bearer $token" -c "$cookies" >/dev/null
    xsrf=$(grep XSRF-TOKEN "$cookies" | awk '{print $NF}')
    response=$(curl -sS --fail-with-body --retry 12 --retry-delay 2 --retry-all-errors --max-time 10 --retry-max-time 60 \
        "http://$KSERVE_UI_BASE_URL/api/namespaces/$KF_PROFILE/inferenceservices" \
        -H "Authorization: Bearer $token" -H "X-XSRF-TOKEN: $xsrf" -H "Cookie: XSRF-TOKEN=$xsrf")
    grep -q "$KSERVE_FIXTURE" <<<"$response" || fail "the Models UI did not list $KSERVE_FIXTURE"
}

models_ui_rejects_unauthorized() {
    local token status
    token=$(kubectl -n default create token default)
    status=$(curl -s -o /dev/null --max-time 10 -w '%{http_code}' \
        "http://$KSERVE_UI_BASE_URL/api/namespaces/$KF_PROFILE/inferenceservices" -H "Authorization: Bearer $token")
    [[ "$status" == 401 || "$status" == 403 ]] || fail "expected 401 or 403 for an unauthorized token, received $status"
}

lifecycle_kserve_ui() {
    ensure_inference_service_fixture
    models_ui_lists_fixture

    RELEASE_NAME=kserve-models-web-application
    RELEASE_NAMESPACE=kserve
    CHART_DIRECTORY=applications/kserve/kserve-ui/helm
    CHANGED_DEPLOYMENTS=(kserve/kserve-models-web-application)
    REINSTALL_COMMAND=(./tests/kserve_ui_helm_install.sh)
    run_release_cycle kserve_ui

    if [[ " ${SELECTED_CHARTS[*]} " != *" kserve "* ]]; then
        kubectl delete inferenceservice "$KSERVE_FIXTURE" -n "$KF_PROFILE"
    fi
}

# Nothing the UI release does not own may change identity, and the user model stays Ready.
identities_kserve_ui() {
    kubectl get namespace kserve -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
    kubectl get inferenceservice "$KSERVE_FIXTURE" -n "$KF_PROFILE" -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
    kubectl get deployments -n kserve -o json | python3 -c '
import json, sys
items = {item["metadata"]["name"]: item["metadata"]["uid"] for item in json.load(sys.stdin)["items"] if item["metadata"]["name"] != "kserve-models-web-application"}
assert "kserve-controller-manager" in items, "the KServe controller is missing"
for name in sorted(items):
    print("deployment", name, items[name])
'
    kubectl wait --for=condition=Ready "inferenceservice/$KSERVE_FIXTURE" -n "$KF_PROFILE" --timeout=120s >/dev/null
}

probe_kserve_ui() {
    models_ui_lists_fixture
}

after_reinstall_kserve_ui() {
    models_ui_rejects_unauthorized
}

lifecycle_kserve() {
    ensure_inference_service_fixture

    RELEASE_NAME=kserve
    RELEASE_NAMESPACE=kserve
    CHART_DIRECTORY=applications/kserve/kserve/helm
    UPGRADE_ARGUMENTS=(--values applications/kserve/kserve/helm/ci/values-platform.yaml)
    CHANGED_DEPLOYMENTS=(kserve/kserve-controller-manager)
    REINSTALL_COMMAND=(./tests/kserve_helm_install.sh)
    run_release_cycle kserve

    kubectl delete inferenceservice "$KSERVE_FIXTURE" -n "$KF_PROFILE"
}

identities_kserve() {
    kubectl get namespace kserve -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
    kubectl get inferenceservice "$KSERVE_FIXTURE" -n "$KF_PROFILE" -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
    kubectl get deployment kserve-models-web-application -n kserve -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
}

# The retained model becomes Ready again and a fresh model is reconciled.
probe_kserve() {
    kubectl wait --for=condition=Ready "inferenceservice/$KSERVE_FIXTURE" -n "$KF_PROFILE" --timeout=300s
    create_inference_service "$KSERVE_FIXTURE-fresh"
    kubectl delete inferenceservice "$KSERVE_FIXTURE-fresh" -n "$KF_PROFILE"
}

# ---------------------------------------------------------------------------
# knative-serving: release knative-serving in kubeflow; fixture from the smoke test
# ---------------------------------------------------------------------------

lifecycle_knative_serving() {
    ./tests/knative_serving_helm_admission_test.sh
    KNATIVE_HELM_KEEP_FIXTURE=true ./tests/knative_serving_helm_smoke_test.sh "$KF_PROFILE"

    RELEASE_NAME=knative-serving
    RELEASE_NAMESPACE=kubeflow
    CHART_DIRECTORY=common/knative/knative-serving/helm
    UPGRADE_ARGUMENTS=(--reset-values --set installation.phase=complete)
    CHANGED_DEPLOYMENTS=(knative-serving/controller)
    REINSTALL_COMMAND=(./tests/knative_serving_helm_install.sh)
    run_release_cycle knative_serving

    kubectl delete services.serving.knative.dev knative-helm-routing -n "$KF_PROFILE" --ignore-not-found
    kubectl delete authorizationpolicy knative-helm-routing -n "$KF_PROFILE" --ignore-not-found
}

identities_knative_serving() {
    kubectl get namespace knative-serving -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
    kubectl get services.serving.knative.dev knative-helm-routing -n "$KF_PROFILE" -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
}

# The exact route body and the missing-token rejection, through the cluster-local gateway.
probe_knative_serving() {
    KNATIVE_HELM_KEEP_FIXTURE=true ./tests/knative_serving_helm_smoke_test.sh "$KF_PROFILE"
}

# ---------------------------------------------------------------------------
# knative-eventing: release knative-eventing in kubeflow; own receiver and PingSource
# ---------------------------------------------------------------------------

EVENTING_NAMESPACE=knative-eventing
EVENTING_FIXTURE=knative-helm-events
EVENTING_PING_PATH="/apis/sources.knative.dev/v1/namespaces/$EVENTING_NAMESPACE/pingsources/$EVENTING_FIXTURE"
EVENTING_CONVERTED_PING_PATH="/apis/sources.knative.dev/v1beta2/namespaces/$EVENTING_NAMESPACE/pingsources/$EVENTING_FIXTURE"
EVENTING_EVENTTYPE_PATH="/apis/eventing.knative.dev/v1beta2/namespaces/$EVENTING_NAMESPACE/eventtypes/$EVENTING_FIXTURE"
EVENTING_CONVERTED_EVENTTYPE_PATH="/apis/eventing.knative.dev/v1beta3/namespaces/$EVENTING_NAMESPACE/eventtypes/$EVENTING_FIXTURE"

# The receiver and the retained PingSource, created once for the whole lifecycle.
create_eventing_fixture() {
    kubectl apply -n "$EVENTING_NAMESPACE" -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: $EVENTING_FIXTURE
spec:
  replicas: 1
  selector:
    matchLabels: {helm-test: $EVENTING_FIXTURE}
  template:
    metadata:
      labels: {helm-test: $EVENTING_FIXTURE}
      annotations:
        sidecar.istio.io/inject: "false"
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 65532
        seccompProfile: {type: RuntimeDefault}
      containers:
      - name: receiver
        image: python:3.12-alpine
        command: [python3, -u, -c]
        args:
        - |
          import http.server, json
          class Receiver(http.server.BaseHTTPRequestHandler):
              def do_POST(self):
                  body = self.rfile.read(int(self.headers['Content-Length']))
                  print(json.dumps({'type': self.headers.get('Ce-Type'), 'data': body.decode()}), flush=True)
                  self.send_response(204)
                  self.end_headers()
          http.server.HTTPServer(('0.0.0.0', 8080), Receiver).serve_forever()
        ports:
        - containerPort: 8080
        resources:
          requests: {cpu: 50m, memory: 32Mi}
          limits: {cpu: 200m, memory: 128Mi}
        securityContext:
          allowPrivilegeEscalation: false
          capabilities:
            drop: [ALL]
---
apiVersion: v1
kind: Service
metadata:
  name: $EVENTING_FIXTURE
spec:
  selector: {helm-test: $EVENTING_FIXTURE}
  ports:
  - port: 80
    targetPort: 8080
---
apiVersion: sources.knative.dev/v1
kind: PingSource
metadata:
  name: $EVENTING_FIXTURE
spec:
  schedule: "* * * * *"
  contentType: application/json
  data: '{"message":"knative-helm-event-ok"}'
  sink:
    ref:
      apiVersion: v1
      kind: Service
      name: $EVENTING_FIXTURE
EOF
    kubectl rollout status "deployment/$EVENTING_FIXTURE" -n "$EVENTING_NAMESPACE" --timeout=120s
    kubectl wait --for=condition=Ready "pingsource/$EVENTING_FIXTURE" -n "$EVENTING_NAMESPACE" --timeout=180s
}

delete_eventing_fixture() {
    kubectl delete pingsource,eventtype,service,deployment "$EVENTING_FIXTURE" -n "$EVENTING_NAMESPACE" --ignore-not-found
}

# Only logs since this invocation count, so a replay cannot pass on old delivery.
check_event_delivery() {
    local started attempt
    started=$(date -u +%Y-%m-%dT%H:%M:%S.%NZ)
    for ((attempt = 0; attempt < 75; attempt++)); do
        if kubectl logs "deployment/$EVENTING_FIXTURE" -n "$EVENTING_NAMESPACE" --since-time="$started" |
            python3 -c 'import json, sys
count = 0
for line in sys.stdin:
    try:
        event = json.loads(line)
        count += event.get("type") == "dev.knative.sources.ping" and json.loads(event.get("data", "null")) == {"message": "knative-helm-event-ok"}
    except (ValueError, TypeError, AttributeError):
        pass
print("Matching newly delivered CloudEvents:", count)
sys.exit(count < 1)'; then
            echo "Eventing delivered the exact PingSource CloudEvent payload."
            return 0
        fi
        sleep 2
    done
    fail "no matching fresh PingSource CloudEvent arrived within 150 seconds"
}

# The adapter specification, generation and Pod identities: the controller owns
# them, and an upgrade must not touch them.
capture_adapter() {
    kubectl get deployment/pingsource-mt-adapter -n "$EVENTING_NAMESPACE" -o json |
        python3 -c 'import json, sys
deployment = json.load(sys.stdin)
print(json.dumps({"spec": deployment["spec"], "generation": deployment["metadata"]["generation"]}, sort_keys=True))'
    kubectl get pods -n "$EVENTING_NAMESPACE" -l eventing.knative.dev/source=ping-source-controller -o json |
        python3 -c 'import json, sys
pods = [pod for pod in json.load(sys.stdin)["items"] if not pod["metadata"].get("deletionTimestamp")]
assert pods and all(
    any(condition["type"] == "Ready" and condition["status"] == "True" for condition in pod.get("status", {}).get("conditions", []))
    for pod in pods
), "Expected healthy, active adapter Pods"
print(json.dumps(sorted(pod["metadata"]["uid"] for pod in pods)))'
}

raw_uid() {
    kubectl get --raw "$1" | python3 -c 'import json, sys; print(json.load(sys.stdin)["metadata"]["uid"])'
}

smoke_knative_eventing() {
    EVIDENCE_PREFIX=smoke-
    DIAGNOSTIC_NAMESPACES=("$EVENTING_NAMESPACE")
    DIAGNOSTIC_DEPLOYMENTS=("$EVENTING_NAMESPACE/eventing-controller" "$EVENTING_NAMESPACE/pingsource-mt-adapter" "$EVENTING_NAMESPACE/$EVENTING_FIXTURE")
    create_eventing_fixture
    check_event_delivery
    delete_eventing_fixture
    echo "knative-eventing smoke passed: fresh PingSource delivery only; no Helm operation ran."
}

lifecycle_knative_eventing() {
    DIAGNOSTIC_DEPLOYMENTS=("$EVENTING_NAMESPACE/$EVENTING_FIXTURE")
    create_eventing_fixture
    kubectl apply -n "$EVENTING_NAMESPACE" -f - <<EOF
apiVersion: eventing.knative.dev/v1beta2
kind: EventType
metadata:
  name: $EVENTING_FIXTURE
spec:
  type: dev.knative.sources.ping
  source: https://knative.example/helm-lifecycle
  reference:
    apiVersion: v1
    kind: Service
    name: $EVENTING_FIXTURE
EOF
    # Both configured conversion APIs must work while the webhook is available.
    kubectl get --raw "$EVENTING_CONVERTED_PING_PATH" >/dev/null
    kubectl get --raw "$EVENTING_CONVERTED_EVENTTYPE_PATH" >/dev/null
    kubectl rollout status deployment/pingsource-mt-adapter -n "$EVENTING_NAMESPACE" --timeout=120s
    capture_adapter >"$(evidence_file adapter-before-upgrades.txt)"

    RELEASE_NAME=knative-eventing
    RELEASE_NAMESPACE=kubeflow
    CHART_DIRECTORY=common/knative/knative-eventing/helm
    UPGRADE_ARGUMENTS=(--reset-values --set installation.phase=complete)
    CHANGED_DEPLOYMENTS=("$EVENTING_NAMESPACE/eventing-controller")
    REINSTALL_COMMAND=(./tests/knative_eventing_helm_install.sh)
    run_release_cycle knative_eventing

    delete_eventing_fixture
}

identities_knative_eventing() {
    local pingsource_uid eventtype_uid
    pingsource_uid=$(raw_uid "$EVENTING_PING_PATH")
    eventtype_uid=$(raw_uid "$EVENTING_EVENTTYPE_PATH")
    echo "pingsource $pingsource_uid"
    echo "eventtype $eventtype_uid"
    kubectl get namespace "$EVENTING_NAMESPACE" -o jsonpath='{.metadata.name}{" "}{.metadata.uid}{"\n"}'
}

# The adapter specification, generation and Pods must be exactly what they were
# after the upgrade (the controller-owned field regression).
after_changed_upgrade_knative_eventing() {
    local after
    after=$(evidence_file adapter-after-changed-upgrade.txt)
    capture_adapter >"$after"
    diff -u "$(evidence_file adapter-before-upgrades.txt)" "$after" ||
        fail "the changed upgrade rewrote the PingSource adapter or replaced its Pod"
}

# Retained definitions do not preserve conversion availability after uninstall.
after_uninstall_knative_eventing() {
    local path conversion
    for path in "$EVENTING_CONVERTED_PING_PATH" "$EVENTING_CONVERTED_EVENTTYPE_PATH"; do
        conversion=$(evidence_file "conversion-after-uninstall-$(basename "${path%/*}")")
        if kubectl get --request-timeout=10s --raw "$path" >"$conversion.out" 2>"$conversion.err"; then
            fail "expected unavailable conversion while eventing-webhook is removed"
        fi
        grep -Eiq 'conversion|webhook|service.*not found' "$conversion.err" || fail "unexpected conversion error"
    done
}

# Pod readiness does not prove the API server trusts the new webhook
# certificate: wait for real conversions of both retained objects.
after_reinstall_knative_eventing() {
    local path deadline
    for path in "$EVENTING_CONVERTED_PING_PATH" "$EVENTING_CONVERTED_EVENTTYPE_PATH"; do
        deadline=$((SECONDS + 120))
        until kubectl get --request-timeout=10s --raw "$path" >/dev/null; do
            (( SECONDS < deadline )) || fail "conversion did not recover within 120 seconds: $path"
            sleep 2
        done
    done
}

# ---------------------------------------------------------------------------

main() {
    local chart function_name
    if [[ "$SMOKE_ONLY" == true ]]; then
        for chart in "${SELECTED_CHARTS[@]}"; do
            declare -F "smoke_${chart//-/_}" >/dev/null || { echo "$chart has no smoke probe" >&2; exit 2; }
        done
    fi
    for chart in "${SELECTED_CHARTS[@]}"; do
        CURRENT_CHART="$chart"
        function_name="${chart//-/_}"
        reset_cycle_descriptor
        DIAGNOSTIC_NAMESPACES=()
        DIAGNOSTIC_DEPLOYMENTS=()
        if [[ "$SMOKE_ONLY" == true ]]; then
            "smoke_$function_name"
        else
            "lifecycle_$function_name"
        fi
        CURRENT_CHART=""
    done
    if [[ "$SMOKE_ONLY" != true ]]; then
        echo "Helm release lifecycle passed for: ${SELECTED_CHARTS[*]}"
    fi
}

main
