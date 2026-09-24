#!/usr/bin/env bash
# Cluster-free tests of the cleanup in tests/workspaces_helm_upgrade_test.sh.
# The script runs unchanged, with stub kubectl and helm executables first on
# PATH. The stubs record every call and imitate a cluster on which the
# kubeflow-workspaces release is deployed; jq is the real one. Whatever happens,
# the script may delete nothing but the namespace that the same run has created.
set -euo pipefail

SCRIPT_DIRECTORY=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
UPGRADE_TEST="${SCRIPT_DIRECTORY}/workspaces_helm_upgrade_test.sh"
TEMPORARY_DIRECTORY=$(mktemp -d)
trap 'rm -rf "$TEMPORARY_DIRECTORY"' EXIT
STUB_DIRECTORY="${TEMPORARY_DIRECTORY}/stubs"
RELEASE_STATE_DIRECTORY="${TEMPORARY_DIRECTORY}/release"
CALL_LOG="${TEMPORARY_DIRECTORY}/calls"
EXIT_STATUS=0
FAILED_TESTS=0

mkdir -p "$STUB_DIRECTORY"

# EVERY_NAMESPACE_EXISTS and EXISTING_NAMESPACE decide which namespace creation
# is answered with AlreadyExists. FAILING_KUBECTL_CALL is the beginning of the
# arguments of a call that has to fail.
cat >"${STUB_DIRECTORY}/kubectl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "kubectl $*" >>"$CALL_LOG"
if [[ -n "$FAILING_KUBECTL_CALL" && "$*" == "$FAILING_KUBECTL_CALL"* ]]; then
  echo "error: prepared failure of kubectl $*" >&2
  exit 1
fi
case "$1 $2" in
"create namespace")
  if [[ "$EVERY_NAMESPACE_EXISTS" == true || "$3" == "$EXISTING_NAMESPACE" ]]; then
    echo "Error from server (AlreadyExists): namespaces \"$3\" already exists" >&2
    exit 1
  fi
  ;;
"create serviceaccount" | "create rolebinding" | "delete namespace") ;;
"get clusterrole")
  echo '{"rules": [{"verbs": ["get"]}], "metadata": {"managedFields": [{"manager": "kube-controller-manager", "fieldsV1": {"f:rules": {}}}]}}'
  ;;
"auth can-i")
  # kubectl auth can-i exits with 1 when the answer is no.
  if [[ "$3 $4" == "get secrets" ]]; then
    echo no
    exit 1
  fi
  echo yes
  ;;
*)
  echo "unexpected kubectl call: $*" >&2
  exit 1
  ;;
esac
EOF

# The release history is one manifest file for every revision. A rendered or
# stored manifest is the path of its chart, so that the changed chart differs.
cat >"${STUB_DIRECTORY}/helm" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
echo "helm $*" >>"$CALL_LOG"
revision=$(cat "${RELEASE_STATE_DIRECTORY}/revision")
case "$1" in
template) echo "chart: $3" ;;
history) echo "revision ${revision}" ;;
status) echo "{\"version\": ${revision}, \"info\": {\"status\": \"deployed\"}}" ;;
get) cat "${RELEASE_STATE_DIRECTORY}/manifest-${!#}" ;;
upgrade)
  echo "chart: $3" >"${RELEASE_STATE_DIRECTORY}/manifest-$((revision + 1))"
  echo "$((revision + 1))" >"${RELEASE_STATE_DIRECTORY}/revision"
  ;;
rollback)
  cp "${RELEASE_STATE_DIRECTORY}/manifest-$3" "${RELEASE_STATE_DIRECTORY}/manifest-$((revision + 1))"
  echo "$((revision + 1))" >"${RELEASE_STATE_DIRECTORY}/revision"
  ;;
*)
  echo "unexpected helm call: $*" >&2
  exit 1
  ;;
esac
EOF
chmod +x "${STUB_DIRECTORY}/kubectl" "${STUB_DIRECTORY}/helm"

# Runs the upgrade test on a release with one revision. The arguments are
# environment assignments of that run.
run_upgrade_test() {
  : >"$CALL_LOG"
  rm -rf "$RELEASE_STATE_DIRECTORY"
  mkdir -p "$RELEASE_STATE_DIRECTORY"
  echo 1 >"${RELEASE_STATE_DIRECTORY}/revision"
  echo "chart: applications/workspaces/helm" >"${RELEASE_STATE_DIRECTORY}/manifest-1"
  EXIT_STATUS=0
  env --unset=WORKSPACES_UPGRADE_AUTHORIZATION_NAMESPACE \
    PATH="${STUB_DIRECTORY}:${PATH}" \
    CALL_LOG="$CALL_LOG" \
    RELEASE_STATE_DIRECTORY="$RELEASE_STATE_DIRECTORY" \
    EVIDENCE_DIRECTORY="${TEMPORARY_DIRECTORY}/evidence" \
    WORKSPACES_UPGRADE_CHART="${TEMPORARY_DIRECTORY}/changed-chart" \
    EVERY_NAMESPACE_EXISTS=false \
    EXISTING_NAMESPACE="" \
    FAILING_KUBECTL_CALL="" \
    "$@" "$UPGRADE_TEST" >"${TEMPORARY_DIRECTORY}/output" 2>&1 || EXIT_STATUS=$?
}

expect() {
  local description="$1"
  shift
  if "$@"; then
    echo "ok: ${description}"
  else
    echo "FAILED: ${description}"
    echo "  exit status of the script: ${EXIT_STATUS}"
    echo "  recorded calls that create a namespace or remove something:"
    {
      grep -E '^kubectl create namespace ' "$CALL_LOG" || true
      removing_calls
    } | sed 's/^/    /'
    FAILED_TESTS=$((FAILED_TESTS + 1))
  fi
}

created_namespaces() {
  sed -n 's/^kubectl create namespace //p' "$CALL_LOG"
}

# Every recorded call that removes something from the cluster.
removing_calls() {
  grep -E '^(kubectl delete|helm uninstall) ' "$CALL_LOG" || true
}

removes_only_the_namespace() {
  [[ "$(removing_calls)" == "kubectl delete namespace $1 --ignore-not-found" ]]
}

is_a_unique_namespace_name() {
  [[ "$1" =~ ^workspaces-upgrade-test-[0-9]+-[0-9]+$ && "${#1}" -le 63 ]]
}

test_a_failed_namespace_creation_removes_nothing() {
  run_upgrade_test EVERY_NAMESPACE_EXISTS=true
  expect "the script fails when its namespace already exists" test "$EXIT_STATUS" -ne 0
  expect "the script tried to create one namespace" test "$(created_namespaces | wc -l)" -eq 1
  expect "nothing is removed after a failed namespace creation" test -z "$(removing_calls)"
}

test_a_failure_after_the_creation_removes_only_the_created_namespace() {
  run_upgrade_test FAILING_KUBECTL_CALL="create serviceaccount"
  expect "the script fails when the ServiceAccount cannot be created" test "$EXIT_STATUS" -ne 0
  expect "a failed run removes exactly the namespace that it created" \
    removes_only_the_namespace "$(created_namespaces)"
}

test_a_completed_run_removes_only_the_created_namespace() {
  run_upgrade_test
  expect "the script succeeds against the stubs" test "$EXIT_STATUS" -eq 0
  expect "two upgrades and one rollback ran" \
    test "$(grep -c -E '^helm (upgrade|rollback) ' "$CALL_LOG")" -eq 3
  expect "the default namespace name \"$(created_namespaces)\" is unique and a valid label" \
    is_a_unique_namespace_name "$(created_namespaces)"
  expect "a completed run removes exactly the namespace that it created" \
    removes_only_the_namespace "$(created_namespaces)"
}

test_a_named_namespace_that_already_exists_is_never_removed() {
  run_upgrade_test WORKSPACES_UPGRADE_AUTHORIZATION_NAMESPACE=team-namespace \
    EXISTING_NAMESPACE=team-namespace
  expect "the script fails when the named namespace already exists" test "$EXIT_STATUS" -ne 0
  expect "the script tried to create the named namespace" \
    test "$(created_namespaces)" == "team-namespace"
  expect "a named namespace that already exists is not removed" test -z "$(removing_calls)"
}

test_a_named_namespace_that_the_run_created_is_removed() {
  run_upgrade_test WORKSPACES_UPGRADE_AUTHORIZATION_NAMESPACE=upgrade-fixture
  expect "the script succeeds with a named namespace" test "$EXIT_STATUS" -eq 0
  expect "the script created the named namespace" \
    test "$(created_namespaces)" == "upgrade-fixture"
  expect "a completed run removes exactly the named namespace that it created" \
    removes_only_the_namespace upgrade-fixture
}

test_a_failed_namespace_creation_removes_nothing
test_a_failure_after_the_creation_removes_only_the_created_namespace
test_a_completed_run_removes_only_the_created_namespace
test_a_named_namespace_that_already_exists_is_never_removed
test_a_named_namespace_that_the_run_created_is_removed

if [[ "$FAILED_TESTS" -ne 0 ]]; then
  echo "${FAILED_TESTS} checks failed"
  exit 1
fi
echo "all checks passed"
