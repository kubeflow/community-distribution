#!/usr/bin/env bash
set -euo pipefail

# Exercise MLflow through the Kubeflow gateway. This intentionally uses only
# projected Kubernetes ServiceAccount tokens; identity headers are supplied by
# the gateway and are never fabricated by this test.
# Prerequisites:
#   - MLflow, Profiles, Dex, OAuth2-Proxy, and the Kubeflow gateway installed
#   - gateway port-forward bound to localhost:8080

PROFILE="${1:-kubeflow-user-example-com}"
WORKSPACE="${2:-$PROFILE}"
BASE_URL="http://localhost:8080/mlflow"
SEARCH_REQUEST_BODY='{"max_results": 100}'
RESPONSE_FILE="$(mktemp)"
SECOND_PROFILE=""
EXPERIMENT_ID=""
SECOND_EXPERIMENT_ID=""

cleanup() {
  local status=$?
  if [[ -n "$EXPERIMENT_ID" ]]; then
    curl --connect-timeout 10 --max-time 30 --fail -sS -o /dev/null \
      -H "Authorization: Bearer ${EDITOR_TOKEN}" \
      -H "X-MLFLOW-WORKSPACE: ${WORKSPACE}" -H 'Content-Type: application/json' \
      -d "{\"experiment_id\":\"${EXPERIMENT_ID}\"}" \
      "$BASE_URL/api/2.0/mlflow/experiments/delete" || status=1
  fi
  if [[ -n "$SECOND_EXPERIMENT_ID" ]]; then
    curl --connect-timeout 10 --max-time 30 --fail -sS -o /dev/null \
      -H "Authorization: Bearer ${SECOND_EDITOR_TOKEN}" \
      -H "X-MLFLOW-WORKSPACE: ${SECOND_PROFILE}" -H 'Content-Type: application/json' \
      -d "{\"experiment_id\":\"${SECOND_EXPERIMENT_ID}\"}" \
      "$BASE_URL/api/2.0/mlflow/experiments/delete" || status=1
  fi
  if [[ -n "$SECOND_PROFILE" ]]; then
    kubectl delete profile "$SECOND_PROFILE" --wait=true --timeout=120s || status=1
  fi
  rm -f "$RESPONSE_FILE"
  exit "$status"
}
trap cleanup EXIT

request() {
  local token="$1"
  local workspace="$2"
  shift 2

  local -a headers=("-H" "Authorization: Bearer ${token}")
  if [[ -n "$workspace" ]]; then
    headers+=("-H" "X-MLFLOW-WORKSPACE: ${workspace}")
  fi

  curl --connect-timeout 10 --max-time 30 -sS -o "$RESPONSE_FILE" -w '%{http_code}' "${headers[@]}" "$@"
}

assert_status() {
  local actual="$1"
  shift
  local expected
  for expected in "$@"; do
    [[ "$actual" == "$expected" ]] && return 0
  done
  echo "FAIL: expected HTTP $* but got HTTP $actual"
  cat "$RESPONSE_FILE"
  exit 1
}

EDITOR_TOKEN="$(kubectl -n "$PROFILE" create token default-editor)"
VIEWER_TOKEN="$(kubectl -n "$PROFILE" create token default-viewer)"
UNAUTHORIZED_TOKEN="$(kubectl -n default create token default)"

# Use the real Profile controller rather than fabricating namespace labels or
# role bindings. Only the generated Profile is owned and deleted by this test.
SECOND_PROFILE="$(kubectl create -f - -o jsonpath='{.metadata.name}' <<'EOF'
apiVersion: kubeflow.org/v1
kind: Profile
metadata:
  generateName: mlflow-isolation-
spec:
  owner:
    kind: User
    name: mlflow-isolation@example.com
EOF
)"
kubectl wait --for=create "namespace/${SECOND_PROFILE}" --timeout=120s
kubectl wait --for=create serviceaccount/default-editor -n "$SECOND_PROFILE" --timeout=120s
kubectl wait --for=jsonpath='{.metadata.labels.app\.kubernetes\.io/part-of}'=kubeflow-profile \
  "namespace/${SECOND_PROFILE}" --timeout=120s
# These are virtual authorization resources, not CRDs. Resource discovery in
# kubectl auth can-i can discard the API group and incorrectly report denial.
for attempt in {1..60}; do
  if kubectl create --raw /apis/authorization.k8s.io/v1/subjectaccessreviews -f - <<EOF | python3 -c 'import json,sys; sys.exit(not json.load(sys.stdin)["status"]["allowed"])'; then
{
  "apiVersion": "authorization.k8s.io/v1",
  "kind": "SubjectAccessReview",
  "spec": {
    "user": "system:serviceaccount:${SECOND_PROFILE}:default-editor",
    "resourceAttributes": {
      "group": "mlflow.kubeflow.org",
      "resource": "experiments",
      "verb": "create",
      "namespace": "${SECOND_PROFILE}"
    }
  }
}
EOF
    break
  fi
  if [[ "$attempt" == 60 ]]; then
    echo "FAIL: Profile editor permissions did not reconcile" >&2
    exit 1
  fi
  sleep 2
done
SECOND_EDITOR_TOKEN="$(kubectl -n "$SECOND_PROFILE" create token default-editor)"

# Routing and gateway authentication. The health endpoint intentionally does
# not exercise MLflow SAR/workspace authorization; Test 2 does that.
echo "Test 1: default-editor can reach MLflow through the gateway..."
STATUS_CODE="$(request "$EDITOR_TOKEN" "$WORKSPACE" "$BASE_URL/health")"
assert_status "$STATUS_CODE" 200
echo "PASS: MLflow health endpoint returned HTTP 200"

echo "Test 2: default-editor can create an experiment..."
EXPERIMENT_NAME="platform-e2e-${SECOND_PROFILE}"
STATUS_CODE="$(request "$EDITOR_TOKEN" "$WORKSPACE" \
  -X POST "$BASE_URL/api/2.0/mlflow/experiments/create" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"${EXPERIMENT_NAME}\"}")"
assert_status "$STATUS_CODE" 200
EXPERIMENT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["experiment_id"])' < "$RESPONSE_FILE")"
echo "PASS: default-editor created experiment ${EXPERIMENT_ID}"

# A token from another namespace must not acquire the Profile's permissions.
echo "Test 3: ServiceAccount from another namespace is denied..."
STATUS_CODE="$(request "$UNAUTHORIZED_TOKEN" "$WORKSPACE" \
  -X POST "$BASE_URL/api/2.0/mlflow/experiments/create" \
  -H 'Content-Type: application/json' \
  -d '{"name":"platform-e2e-unauthorized"}')"
assert_status "$STATUS_CODE" 403
echo "PASS: unauthorized ServiceAccount received HTTP 403"

# Gateway authentication must reject requests without a bearer token on a real
# MLflow API route, not on the unprotected health endpoint.
echo "Test 4: request without a token is denied..."
STATUS_CODE="$(curl --connect-timeout 10 --max-time 30 -sS -o "$RESPONSE_FILE" -w '%{http_code}' \
  -X POST "$BASE_URL/api/2.0/mlflow/experiments/search" \
  -H 'Content-Type: application/json' \
  -d "$SEARCH_REQUEST_BODY")"
assert_status "$STATUS_CODE" 302 401 403
echo "PASS: unauthenticated request received HTTP ${STATUS_CODE}"

# The editor must not access a non-Profile namespace excluded by the
# workspaceLabelSelector, separately from the cross-Profile checks below.
echo "Test 5: non-Profile workspace is isolated..."
STATUS_CODE="$(request "$EDITOR_TOKEN" default \
  -X POST "$BASE_URL/api/2.0/mlflow/experiments/search" \
  -H 'Content-Type: application/json' \
  -d "$SEARCH_REQUEST_BODY")"
assert_status "$STATUS_CODE" 403 404
echo "PASS: non-Profile workspace was not accessible (HTTP ${STATUS_CODE})"

# The aggregated Profile viewer role can read but cannot mutate MLflow data.
echo "Test 6: default-viewer can list experiments..."
STATUS_CODE="$(request "$VIEWER_TOKEN" "$WORKSPACE" \
  -X POST "$BASE_URL/api/2.0/mlflow/experiments/search" \
  -H 'Content-Type: application/json' \
  -d "$SEARCH_REQUEST_BODY")"
assert_status "$STATUS_CODE" 200
python3 - "$EXPERIMENT_ID" "$RESPONSE_FILE" <<'PY'
import json
import sys
with open(sys.argv[2]) as response:
    experiments = json.load(response)["experiments"]
assert sys.argv[1] in {experiment["experiment_id"] for experiment in experiments}
PY
echo "PASS: default-viewer listed experiments"

echo "Test 7: default-viewer can get an experiment..."
STATUS_CODE="$(request "$VIEWER_TOKEN" "$WORKSPACE" \
  "$BASE_URL/api/2.0/mlflow/experiments/get?experiment_id=${EXPERIMENT_ID}")"
assert_status "$STATUS_CODE" 200
python3 - "$EXPERIMENT_ID" "$RESPONSE_FILE" <<'PY'
import json
import sys
with open(sys.argv[2]) as response:
    assert json.load(response)["experiment"]["experiment_id"] == sys.argv[1]
PY
echo "PASS: default-viewer got experiment ${EXPERIMENT_ID}"

echo "Test 8: default-viewer cannot create an experiment..."
STATUS_CODE="$(request "$VIEWER_TOKEN" "$WORKSPACE" \
  -X POST "$BASE_URL/api/2.0/mlflow/experiments/create" \
  -H 'Content-Type: application/json' \
  -d '{"name":"platform-e2e-viewer-mutation"}')"
assert_status "$STATUS_CODE" 403
echo "PASS: default-viewer received HTTP 403 for mutation"

echo "Test 9: the second Profile can create its own experiment..."
STATUS_CODE="$(request "$SECOND_EDITOR_TOKEN" "$SECOND_PROFILE" \
  -X POST "$BASE_URL/api/2.0/mlflow/experiments/create" \
  -H 'Content-Type: application/json' -d "{\"name\":\"${EXPERIMENT_NAME}\"}")"
assert_status "$STATUS_CODE" 200
SECOND_EXPERIMENT_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["experiment_id"])' < "$RESPONSE_FILE")"

echo "Test 10: workspace discovery is filtered by Profile permissions..."
for identity in first second; do
  if [[ "$identity" == first ]]; then
    TOKEN="$EDITOR_TOKEN"; OWN_WORKSPACE="$WORKSPACE"; OTHER_WORKSPACE="$SECOND_PROFILE"
  else
    TOKEN="$SECOND_EDITOR_TOKEN"; OWN_WORKSPACE="$SECOND_PROFILE"; OTHER_WORKSPACE="$WORKSPACE"
  fi
  STATUS_CODE="$(request "$TOKEN" "" "$BASE_URL/api/3.0/mlflow/workspaces")"
  assert_status "$STATUS_CODE" 200
  python3 - "$OWN_WORKSPACE" "$OTHER_WORKSPACE" "$RESPONSE_FILE" <<'PY'
import json
import sys
with open(sys.argv[3]) as response:
    names = {workspace["name"] for workspace in json.load(response)["workspaces"]}
assert sys.argv[1] in names, "The authorized Profile is missing"
assert sys.argv[2] not in names, "Another Profile was disclosed"
PY

  echo "Test 11: ${identity} Profile cannot read or write the other workspace..."
  STATUS_CODE="$(request "$TOKEN" "$OTHER_WORKSPACE" \
    -X POST "$BASE_URL/api/2.0/mlflow/experiments/search" \
    -H 'Content-Type: application/json' -d "$SEARCH_REQUEST_BODY")"
  assert_status "$STATUS_CODE" 200 403 404
  if [[ "$STATUS_CODE" == 200 ]]; then
    python3 -c 'import json,sys; result=json.load(sys.stdin); assert not result.get("experiments"), "Cross-Profile data leak"; assert not result.get("next_page_token")' < "$RESPONSE_FILE"
  fi
  STATUS_CODE="$(request "$TOKEN" "$OTHER_WORKSPACE" \
    -X POST "$BASE_URL/api/2.0/mlflow/experiments/create" \
    -H 'Content-Type: application/json' -d '{"name":"cross-profile-must-not-create"}')"
  assert_status "$STATUS_CODE" 403
done

echo "Test 12: gateway identity cannot be replaced with a caller-supplied user header..."
STATUS_CODE="$(request "$SECOND_EDITOR_TOKEN" "$WORKSPACE" \
  -H "kubeflow-userid: system:serviceaccount:${PROFILE}:default-editor" \
  -X POST "$BASE_URL/api/2.0/mlflow/experiments/create" \
  -H 'Content-Type: application/json' -d '{"name":"forged-identity-must-not-create"}')"
assert_status "$STATUS_CODE" 403

echo "=== All MLflow platform tests passed! ==="
