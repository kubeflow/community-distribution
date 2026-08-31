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
RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$RESPONSE_FILE"' EXIT

request() {
  local token="$1"
  local workspace="$2"
  shift 2

  local -a headers=("-H" "Authorization: Bearer ${token}")
  if [[ -n "$workspace" ]]; then
    headers+=("-H" "X-MLFLOW-WORKSPACE: ${workspace}")
  fi

  curl -sS -o "$RESPONSE_FILE" -w '%{http_code}' "${headers[@]}" "$@"
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

# Routing and gateway authentication. The health endpoint intentionally does
# not exercise MLflow SAR/workspace authorization; Test 2 does that.
echo "Test 1: default-editor can reach MLflow through the gateway..."
STATUS_CODE="$(request "$EDITOR_TOKEN" "$WORKSPACE" "$BASE_URL/health")"
assert_status "$STATUS_CODE" 200
echo "PASS: MLflow health endpoint returned HTTP 200"

echo "Test 2: default-editor can create an experiment..."
EXPERIMENT_NAME="platform-e2e-$(date +%s)"
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
STATUS_CODE="$(curl -sS -o "$RESPONSE_FILE" -w '%{http_code}' \
  -X POST "$BASE_URL/api/2.0/mlflow/experiments/search" \
  -H 'Content-Type: application/json' \
  -d '{}')"
assert_status "$STATUS_CODE" 302 401 403
echo "PASS: unauthenticated request received HTTP ${STATUS_CODE}"

# The editor must not access a non-Profile namespace excluded by the
# workspaceLabelSelector. With one Profile in this CI lane, this checks
# workspace-selector isolation, not Profile-to-Profile RBAC isolation.
echo "Test 5: non-Profile workspace is isolated..."
STATUS_CODE="$(request "$EDITOR_TOKEN" default \
  -X POST "$BASE_URL/api/2.0/mlflow/experiments/search" \
  -H 'Content-Type: application/json' \
  -d '{}')"
assert_status "$STATUS_CODE" 403 404
echo "PASS: non-Profile workspace was not accessible (HTTP ${STATUS_CODE})"

# The aggregated Profile viewer role can read but cannot mutate MLflow data.
echo "Test 6: default-viewer can list experiments..."
STATUS_CODE="$(request "$VIEWER_TOKEN" "$WORKSPACE" \
  -X POST "$BASE_URL/api/2.0/mlflow/experiments/search" \
  -H 'Content-Type: application/json' \
  -d '{}')"
assert_status "$STATUS_CODE" 200
echo "PASS: default-viewer listed experiments"

echo "Test 7: default-viewer can get an experiment..."
STATUS_CODE="$(request "$VIEWER_TOKEN" "$WORKSPACE" \
  "$BASE_URL/api/2.0/mlflow/experiments/get?experiment_id=${EXPERIMENT_ID}")"
assert_status "$STATUS_CODE" 200
echo "PASS: default-viewer got experiment ${EXPERIMENT_ID}"

echo "Test 8: default-viewer cannot create an experiment..."
STATUS_CODE="$(request "$VIEWER_TOKEN" "$WORKSPACE" \
  -X POST "$BASE_URL/api/2.0/mlflow/experiments/create" \
  -H 'Content-Type: application/json' \
  -d '{"name":"platform-e2e-viewer-mutation"}')"
assert_status "$STATUS_CODE" 403
echo "PASS: default-viewer received HTTP 403 for mutation"

echo "=== All MLflow platform tests passed! ==="
