#!/bin/bash
set -euxo pipefail

# Test Model Registry API and UI integration
# This script can be used for local testing without GitHub Actions
# Prerequisites: Model Registry must be installed (run model_registry_install.sh first)
# Usage: ./tests/model_registry_test.sh

echo "=== Model Registry Integration Tests ==="

# ---- Test 1: Direct API access via port-forward ----
# Note: port-forward bypasses the Istio sidecar, so AuthorizationPolicy is not
# enforced here. These tests validate the Model Registry REST API functionality.
# AP enforcement is validated through the gateway tests (Test 6).
echo "Test 1: Direct Model Registry API access..."
nohup kubectl port-forward svc/model-registry-service -n kubeflow 8081:8080 &
timeout 30s bash -c 'until curl -s localhost:8081 > /dev/null 2>&1; do sleep 1; done'

# ---- Test 2: Create a RegisteredModel ----
echo ""
echo "Test 2: Create a RegisteredModel..."
CREATE_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
  "http://localhost:8081/api/model_registry/v1alpha3/registered_models" \
  -H "Content-Type: application/json" \
  -d '{"name": "test-model", "description": "Model for CI testing"}')

CREATE_HTTP_CODE=$(echo "$CREATE_RESPONSE" | tail -1)
CREATE_BODY=$(echo "$CREATE_RESPONSE" | sed '$d')

if [ "$CREATE_HTTP_CODE" -eq 201 ]; then
    echo "PASS: RegisteredModel created (HTTP $CREATE_HTTP_CODE)"
else
    echo "FAIL: Expected HTTP 201, got: $CREATE_HTTP_CODE"
    echo "Response: $CREATE_BODY"
    exit 1
fi

# Extract the model ID from response
MODEL_ID=$(echo "$CREATE_BODY" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
echo "Created RegisteredModel ID: $MODEL_ID"

# ---- Test 3: Create a ModelVersion under the RegisteredModel ----
echo ""
echo "Test 3: Create a ModelVersion..."
VERSION_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
  "http://localhost:8081/api/model_registry/v1alpha3/registered_models/${MODEL_ID}/versions" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"v1\", \"description\": \"Test version for CI\", \"registeredModelId\": \"${MODEL_ID}\"}")

VERSION_HTTP_CODE=$(echo "$VERSION_RESPONSE" | tail -1)
VERSION_BODY=$(echo "$VERSION_RESPONSE" | sed '$d')

if [ "$VERSION_HTTP_CODE" -eq 201 ]; then
    echo "PASS: ModelVersion created (HTTP $VERSION_HTTP_CODE)"
else
    echo "FAIL: Expected HTTP 201, got: $VERSION_HTTP_CODE"
    echo "Response: $VERSION_BODY"
    exit 1
fi

VERSION_ID=$(echo "$VERSION_BODY" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
echo "Created ModelVersion ID: $VERSION_ID"

# ---- Test 4: Create a ModelArtifact under the ModelVersion ----
echo ""
echo "Test 4: Create a ModelArtifact..."
ARTIFACT_RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
  "http://localhost:8081/api/model_registry/v1alpha3/model_versions/${VERSION_ID}/artifacts" \
  -H "Content-Type: application/json" \
  -d "{\"name\": \"test-artifact\", \"description\": \"Test artifact for CI\", \"uri\": \"s3://dummy-bucket/model.tar.gz\", \"modelFormatName\": \"sklearn\", \"modelFormatVersion\": \"1.0\", \"artifactType\": \"model-artifact\", \"modelVersionId\": \"${VERSION_ID}\"}")

ARTIFACT_HTTP_CODE=$(echo "$ARTIFACT_RESPONSE" | tail -1)
ARTIFACT_BODY=$(echo "$ARTIFACT_RESPONSE" | sed '$d')

if [ "$ARTIFACT_HTTP_CODE" -eq 201 ]; then
    echo "PASS: ModelArtifact created (HTTP $ARTIFACT_HTTP_CODE)"
else
    echo "FAIL: Expected HTTP 201, got: $ARTIFACT_HTTP_CODE"
    echo "Response: $ARTIFACT_BODY"
    exit 1
fi

# ---- Test 5: Verify model appears in listing ----
echo ""
echo "Test 5: Verify RegisteredModel appears in listing..."
LIST_RESPONSE=$(curl -s -w "\n%{http_code}" \
  "http://localhost:8081/api/model_registry/v1alpha3/registered_models?pageSize=100&orderBy=ID&sortOrder=DESC")

LIST_HTTP_CODE=$(echo "$LIST_RESPONSE" | tail -1)
LIST_BODY=$(echo "$LIST_RESPONSE" | sed '$d')

if [ "$LIST_HTTP_CODE" -eq 200 ]; then
    echo "PASS: Model listing API responding (HTTP $LIST_HTTP_CODE)"
else
    echo "FAIL: Model listing returned unexpected status: $LIST_HTTP_CODE"
    exit 1
fi

if echo "$LIST_BODY" | grep -q "test-model"; then
    echo "PASS: Created model 'test-model' found in listing"
else
    echo "FAIL: Created model 'test-model' NOT found in listing"
    echo "Response: $(echo "$LIST_BODY" | head -c 500)"
    exit 1
fi


# ---- Test 6: API access through Istio gateway ----
# These tests validate the AuthorizationPolicy enforcement through the Istio mesh.
# The hardened model-registry-service AP uses the KFP dual-path pattern:
#   Rule 1: Allow ingress-gateway (authservice authenticates external users)
#   Rule 2: Allow internal K8s JWT, block kubeflow-userid header spoofing
echo ""
echo "Test 6: Model Registry API via Istio gateway..."
INGRESS_GATEWAY_SERVICE=$(kubectl get svc --namespace istio-system \
  --selector="app=istio-ingressgateway" \
  --output jsonpath='{.items[0].metadata.name}')

nohup kubectl port-forward --namespace istio-system "svc/${INGRESS_GATEWAY_SERVICE}" 8080:80 &
timeout 30s bash -c 'until curl -s localhost:8080 > /dev/null 2>&1; do sleep 1; done'

# Test authenticated access (authorized SA)
export KF_PROFILE=kubeflow-user-example-com
export KF_TOKEN="$(kubectl -n "$KF_PROFILE" create token default-editor)"

STATUS_CODE=$(curl -s -o /dev/stderr -w "%{http_code}" \
    "localhost:8080/model-registry/api/v1/model_registry?namespace=${KF_PROFILE}" \
    -H "Authorization: Bearer ${KF_TOKEN}" 2>/dev/null)

if [ "$STATUS_CODE" -eq 200 ]; then
    echo "PASS: Authorized access to Model Registry via gateway (HTTP $STATUS_CODE)"
else
    echo "FAIL: Expected HTTP 200 for authorized access, got: $STATUS_CODE"
    exit 1
fi

# Test unauthorized access (default SA - should be 403)
export KF_TOKEN_UNAUTH="$(kubectl -n default create token default)"

STATUS_CODE=$(curl -s -o /dev/stderr -w "%{http_code}" \
    "localhost:8080/model-registry/api/v1/model_registry?namespace=${KF_PROFILE}" \
    -H "Authorization: Bearer ${KF_TOKEN_UNAUTH}" 2>/dev/null)

if [ "$STATUS_CODE" -eq 403 ]; then
    echo "PASS: Unauthorized access correctly denied (HTTP $STATUS_CODE)"
else
    echo "FAIL: Expected HTTP 403 for unauthorized access, got: $STATUS_CODE"
    exit 1
fi


echo ""
echo "=== All Model Registry tests passed! ==="
