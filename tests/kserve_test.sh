#!/bin/bash
set -euxo pipefail

NAMESPACE=${1:-kubeflow-user-example-com}
SCRIPT_DIRECTORY="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

export KSERVE_INGRESS_HOST_PORT=${KSERVE_INGRESS_HOST_PORT:-localhost:8080}
export KSERVE_M2M_TOKEN="$(kubectl -n ${NAMESPACE} create token default-editor)"
export KSERVE_TEST_NAMESPACE=${NAMESPACE}

kubectl patch clusterstoragecontainer default --type=merge --patch '{
  "spec": {
    "container": {
      "securityContext": {
        "allowPrivilegeEscalation": false,
        "capabilities": {"drop": ["ALL"]},
        "runAsNonRoot": true,
        "runAsUser": 1000,
        "seccompProfile": {"type": "RuntimeDefault"}
      }
    }
  }
}'
kubectl get clusterstoragecontainer default -o yaml

# ============================================================
# Test 1: Model Prediction via KServe Python SDK
# ============================================================
# Runs kserve_sklearn_test.py which independently deploys an sklearn
# InferenceService, predicts via host-based routing, asserts the
# output, and deletes the InferenceService.
pip install -q pytest
python -m pytest "${SCRIPT_DIRECTORY}/kserve_sklearn_test.py" -vs --log-cli-level=INFO

# ============================================================
# Test 2: Ingress Gateway -- Path-based & Host-based Routing (curl)
# ============================================================
# Re-create the AuthorizationPolicy before the InferenceService so the predictor
# sidecar receives the allow rule during startup.
# WARNING: allow-all rule -- the predictor sidecar has no RequestAuthentication,
# so requestPrincipals: ["*"] cannot work here. Security is enforced at the
# ingress gateway, which validates the JWT before forwarding traffic.
cat <<EOF | kubectl apply -f -
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: allow-isvc-sklearn
  namespace: ${NAMESPACE}
spec:
  action: ALLOW
  rules:
  - {}
  selector:
    matchLabels:
      serving.knative.dev/service: isvc-sklearn-predictor
EOF

# Re-deploy the InferenceService for bash/curl tests (pytest deleted it).
cat <<EOF | kubectl apply -f -
apiVersion: "serving.kserve.io/v1beta1"
kind: "InferenceService"
metadata:
  name: "isvc-sklearn"
  namespace: ${NAMESPACE}
spec:
  predictor:
    sklearn:
      storageUri: "gs://kfserving-examples/models/sklearn/1.0/model"
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop:
          - ALL
        runAsNonRoot: true
        runAsUser: 1000
        seccompProfile:
          type: RuntimeDefault
      resources:
        requests:
          cpu: "50m"
          memory: "128Mi"
        limits:
          cpu: "100m"
          memory: "256Mi"
EOF

kubectl wait --for=condition=Ready inferenceservice/isvc-sklearn -n ${NAMESPACE} --timeout=300s

# Wait for AuthorizationPolicy to propagate through Envoy by polling
# the host-based route (path-based may return 404 before the route is
# configured, which would false-positive exit the loop).
echo "Waiting for AuthorizationPolicy to propagate..."
STABLE_POLL_COUNT=0
for attempt in $(seq 1 24); do
  POLL_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer ${KSERVE_M2M_TOKEN}" \
    -H "Host: isvc-sklearn.${NAMESPACE}.example.com" \
    -H "Content-Type: application/json" \
    "http://${KSERVE_INGRESS_HOST_PORT}/v1/models/isvc-sklearn:predict" \
    -d '{"instances": [[6.8, 2.8, 4.8, 1.4]]}')
  if [ "$POLL_CODE" != "403" ]; then
    STABLE_POLL_COUNT=$((STABLE_POLL_COUNT + 1))
    if [ "$STABLE_POLL_COUNT" -eq 2 ]; then
      echo "AuthorizationPolicy propagated after $((attempt * 5)) seconds (HTTP ${POLL_CODE})"
      break
    fi
  else
    STABLE_POLL_COUNT=0
  fi
  if [ "$attempt" -eq 24 ]; then
    echo "FAIL: AuthorizationPolicy did not propagate within 120 seconds"
    exit 1
  fi
  sleep 5
done

# --- Test 2a: PATH-BASED routing ---
# Path-based routing uses the native pathTemplate (/serving/<ns>/<name>/)
# configured in the inferenceservice-config ConfigMap patch
# (applications/kserve/kserve/kustomization.yaml). KServe auto-generates
# a VirtualService on kubeflow-gateway where M2M RequestAuthentication
# validates the JWT.

# Request without token should be rejected
RESPONSE=$(curl -s -w "\n%{http_code}" \
 -H "Content-Type: application/json" \
 "http://${KSERVE_INGRESS_HOST_PORT}/serving/${NAMESPACE}/isvc-sklearn/v1/models/isvc-sklearn:predict" \
 -d '{"instances": [[6.8, 2.8, 4.8, 1.4]]}')
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 2a path-based (no token): HTTP $HTTP_CODE | ${BODY:0:200}"

if [ "$HTTP_CODE" != "403" ] && [ "$HTTP_CODE" != "302" ]; then
  echo "FAIL: Path-based: Expected 403/302 without token, got $HTTP_CODE"
  exit 1
fi

# Request with valid token should succeed
RESPONSE=$(curl -s -w "\n%{http_code}" \
 -H "Authorization: Bearer ${KSERVE_M2M_TOKEN}" \
 -H "Content-Type: application/json" \
 "http://${KSERVE_INGRESS_HOST_PORT}/serving/${NAMESPACE}/isvc-sklearn/v1/models/isvc-sklearn:predict" \
 -d '{"instances": [[6.8, 2.8, 4.8, 1.4], [6.0, 3.4, 4.5, 1.6]]}')
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 2a path-based (with token): HTTP $HTTP_CODE | ${BODY:0:200}"

if [ "$HTTP_CODE" != "200" ] && [ "$HTTP_CODE" != "404" ] && [ "$HTTP_CODE" != "503" ]; then
  echo "FAIL: Path-based: Expected 200/404/503 with token, got $HTTP_CODE"
  exit 1
fi

# --- Test 2b: HOST-BASED routing (security verification) ---
HOST_HEADER="Host: isvc-sklearn.${NAMESPACE}.example.com"

# Request without token should be rejected
RESPONSE=$(curl -s -w "\n%{http_code}" \
 -H "${HOST_HEADER}" \
 -H "Content-Type: application/json" \
 "http://${KSERVE_INGRESS_HOST_PORT}/v1/models/isvc-sklearn:predict" \
 -d '{"instances": [[6.8, 2.8, 4.8, 1.4]]}')
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 2b host-based (no token): HTTP $HTTP_CODE | ${BODY:0:200}"

if [ "$HTTP_CODE" != "403" ] && [ "$HTTP_CODE" != "302" ]; then
  echo "FAIL: Host-based: Expected 403/302 without token, got $HTTP_CODE"
  exit 1
fi

# Request with valid token should succeed (the AuthorizationPolicy
# allows any request with a valid JWT principal)
RESPONSE=$(curl -s -w "\n%{http_code}" \
 -H "Authorization: Bearer ${KSERVE_M2M_TOKEN}" \
 -H "${HOST_HEADER}" \
 -H "Content-Type: application/json" \
 "http://${KSERVE_INGRESS_HOST_PORT}/v1/models/isvc-sklearn:predict" \
 -d '{"instances": [[6.8, 2.8, 4.8, 1.4], [6.0, 3.4, 4.5, 1.6]]}')
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 2b host-based (with token): HTTP $HTTP_CODE | ${BODY:0:200}"

if [ "$HTTP_CODE" != "200" ] && [ "$HTTP_CODE" != "404" ] && [ "$HTTP_CODE" != "503" ]; then
  echo "FAIL: Host-based: Expected 200/404/503 with token, got $HTTP_CODE"
  exit 1
fi

kubectl delete inferenceservice isvc-sklearn -n ${NAMESPACE}
kubectl delete authorizationpolicy allow-isvc-sklearn -n ${NAMESPACE}

# ============================================================
# Test 3: KServe Models Web Application API
# ============================================================
kubectl wait --for=condition=Available --timeout=10s -n kubeflow deployment/kserve-models-web-application

TOKEN="$(kubectl -n ${NAMESPACE} create token default-editor)"
BASE_URL="localhost:8080/kserve-endpoints"

cat <<EOF | kubectl apply -f -
apiVersion: "serving.kserve.io/v1beta1"
kind: "InferenceService"
metadata:
  name: "sklearn-iris"
  namespace: ${NAMESPACE}
spec:
  predictor:
    sklearn:
      storageUri: "gs://kfserving-examples/models/sklearn/1.0/model"
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop:
          - ALL
        runAsNonRoot: true
        runAsUser: 1000
        seccompProfile:
          type: RuntimeDefault
      resources:
        requests:
          cpu: "50m"
          memory: "128Mi"
        limits:
          cpu: "100m"
          memory: "256Mi"
EOF

kubectl wait --for=condition=Ready inferenceservice/sklearn-iris -n ${NAMESPACE} --timeout=120s
kubectl get inferenceservice sklearn-iris -n ${NAMESPACE}

# Get XSRF token for API calls
curl -s "http://${BASE_URL}/" \
  -H "Authorization: Bearer ${TOKEN}" \
  -v -c /tmp/kserve_xcrf.txt 2>&1 | grep -i "set-cookie"
XSRFTOKEN=$(grep XSRF-TOKEN /tmp/kserve_xcrf.txt | awk '{print $NF}')

RESPONSE=$(curl -s --fail-with-body \
  "${BASE_URL}/api/namespaces/${NAMESPACE}/inferenceservices" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "X-XSRF-TOKEN: ${XSRFTOKEN}" \
  -H "Cookie: XSRF-TOKEN=${XSRFTOKEN}")

echo "$RESPONSE" | grep -q "sklearn-iris"
kubectl get inferenceservice sklearn-iris -n ${NAMESPACE}
READY=$(kubectl get isvc sklearn-iris -n ${NAMESPACE} -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
[[ "$READY" == "True" ]] || {
  echo "FAILURE: InferenceService sklearn-iris Ready status is: $READY"
  exit 1
}

kubectl delete inferenceservice sklearn-iris -n ${NAMESPACE}

# Test unauthorized access to models web application
UNAUTHORIZED_TOKEN="$(kubectl -n default create token default)"
RESPONSE=$(curl -s -w "\n%{http_code}" "${BASE_URL}/api/namespaces/${NAMESPACE}/inferenceservices" -H "Authorization: Bearer ${UNAUTHORIZED_TOKEN}")
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 3 models web application (unauthorized): HTTP $HTTP_CODE | ${BODY:0:200}"
[[ "$HTTP_CODE" == "403" || "$HTTP_CODE" == "401" ]] || { echo "FAILURE: Expected 401/403, got $HTTP_CODE"; exit 1; }
echo "Models Web Application: Token from unauthorized ServiceAccount cannot list InferenceServices in $NAMESPACE namespace."

# ============================================================
# Test 4: Knative Service authentication via cluster-local-gateway
# ============================================================
cat <<EOF | kubectl apply -f -
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: secure-model-predictor
  namespace: ${NAMESPACE}
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "1"
    spec:
      containers:
      - image: gcr.io/knative-samples/helloworld-go
        ports:
        - containerPort: 8080
        env:
        - name: TARGET
          value: "Secure KServe Model"
        securityContext:
          runAsUser: 65534
          allowPrivilegeEscalation: false
          runAsNonRoot: true
          seccompProfile:
            type: RuntimeDefault
          capabilities:
            drop: ["ALL"]
EOF

kubectl wait --for=condition=Ready ksvc/secure-model-predictor -n ${NAMESPACE} --timeout=120s

# Verify unauthenticated access is blocked
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Host: secure-model-predictor.${NAMESPACE}.svc.cluster.local" \
    "http://${KSERVE_INGRESS_HOST_PORT}/")
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 4 Knative Service (no token): HTTP $HTTP_CODE | ${BODY:0:200}"

if [ "$HTTP_CODE" != "403" ]; then
    echo "FAIL: Unauthenticated access should return 403, got $HTTP_CODE"
    exit 1
fi

# Verify invalid token is rejected
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Host: secure-model-predictor.${NAMESPACE}.svc.cluster.local" \
    -H "Authorization: Bearer invalid-token" \
    "http://${KSERVE_INGRESS_HOST_PORT}/")
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 4 Knative Service (invalid token): HTTP $HTTP_CODE | ${BODY:0:200}"

if [ "$HTTP_CODE" != "401" ] && [ "$HTTP_CODE" != "403" ]; then
    echo "FAIL: Invalid token should return 401/403, got $HTTP_CODE"
    exit 1
fi

# ============================================================
# Test 5: Cluster-local-gateway requires authentication
# ============================================================
kubectl port-forward -n istio-system svc/cluster-local-gateway 8081:80 &
PORT_FORWARD_PID=$!
sleep 5

RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Host: secure-model-predictor.${NAMESPACE}.svc.cluster.local" \
    -H "Authorization: Bearer $KSERVE_M2M_TOKEN" \
    "http://localhost:8081/")
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 5 cluster-local (with token): HTTP $HTTP_CODE | ${BODY:0:200}"

RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Host: secure-model-predictor.${NAMESPACE}.svc.cluster.local" \
    "http://localhost:8081/")
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 5 cluster-local (no token): HTTP $HTTP_CODE | ${BODY:0:200}"

if [ "$HTTP_CODE" != "403" ]; then
    echo "FAIL: Cluster-local-gateway unauthenticated access should return 403, got $HTTP_CODE"
    exit 1
fi

# ============================================================
# Test 6: Namespace isolation - attacker should NOT have access
# ============================================================
ATTACKER_NAMESPACE="attacker-namespace"
kubectl create namespace ${ATTACKER_NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: attacker-service-account
  namespace: ${ATTACKER_NAMESPACE}
EOF

# Unauthenticated request from attacker namespace should be REJECTED
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Host: secure-model-predictor.${NAMESPACE}.svc.cluster.local" \
    "http://localhost:8081/")
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 6 namespace isolation (attacker, no token): HTTP $HTTP_CODE | ${BODY:0:200}"

if [ "$HTTP_CODE" == "200" ]; then
    echo "FAIL: Unauthenticated attacker namespace request should be rejected, got $HTTP_CODE"
    exit 1
fi

# Authenticated request from attacker namespace should ALSO be REJECTED
ATTACKER_TOKEN=$(kubectl -n ${ATTACKER_NAMESPACE} create token attacker-service-account)

RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Host: secure-model-predictor.${NAMESPACE}.svc.cluster.local" \
    -H "Authorization: Bearer $ATTACKER_TOKEN" \
    "http://localhost:8081/")
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 6 namespace isolation (attacker, with token): HTTP $HTTP_CODE | ${BODY:0:200}"

if [ "$HTTP_CODE" == "200" ]; then
    echo "FAIL: Attacker namespace token should be rejected (namespace isolation), got $HTTP_CODE"
    exit 1
fi

kubectl delete ksvc secure-model-predictor -n ${NAMESPACE}
kubectl delete namespace ${ATTACKER_NAMESPACE}

# ============================================================
# Test 7: Raw Deployment Mode -- host-based routing
# ============================================================
# Deploy an sklearn model in Standard (raw deployment) mode. KServe creates a
# Deployment + Service + Ingress (not Knative/VirtualService).
# NOTE: KServe v0.16 renamed "RawDeployment" to "Standard" and
# "Serverless" to "Knative". Using the old names causes the
# validation webhook to reject status updates during deletion
# (kserve/kserve#4710, kserve/kserve#4798).
# Path-based routing for raw deployment requires ingressPathTemplate
# (kserve/kserve#5090, not yet merged), so this test uses host-based
# routing only.
# WARNING: allow-all rule -- same rationale as Test 2.
# Uses serving.kserve.io/inferenceservice label (works for both
# serverless and raw deployment modes).
cat <<EOF | kubectl apply -f -
apiVersion: security.istio.io/v1beta1
kind: AuthorizationPolicy
metadata:
  name: allow-isvc-sklearn-raw
  namespace: ${NAMESPACE}
spec:
  action: ALLOW
  rules:
  - {}
  selector:
    matchLabels:
      serving.kserve.io/inferenceservice: isvc-sklearn-raw
EOF

cat <<EOF | kubectl apply -f -
apiVersion: "serving.kserve.io/v1beta1"
kind: "InferenceService"
metadata:
  name: "isvc-sklearn-raw"
  namespace: ${NAMESPACE}
  annotations:
    serving.kserve.io/deploymentMode: Standard
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

kubectl wait --for=condition=Ready inferenceservice/isvc-sklearn-raw \
  -n ${NAMESPACE} --timeout=300s

RAW_HOST="isvc-sklearn-raw-${NAMESPACE}.example.com"

# Wait for AuthorizationPolicy to propagate through Envoy by polling
# until an authenticated request is no longer denied by the default policy.
echo "Waiting for AuthorizationPolicy to propagate..."
STABLE_POLL_COUNT=0
for attempt in $(seq 1 24); do
  POLL_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer ${KSERVE_M2M_TOKEN}" \
    -H "Host: ${RAW_HOST}" \
    -H "Content-Type: application/json" \
    "http://${KSERVE_INGRESS_HOST_PORT}/v1/models/isvc-sklearn-raw:predict" \
    -d '{"instances": [[6.8, 2.8, 4.8, 1.4]]}')
  if [ "$POLL_CODE" != "403" ]; then
    STABLE_POLL_COUNT=$((STABLE_POLL_COUNT + 1))
    if [ "$STABLE_POLL_COUNT" -eq 2 ]; then
      echo "AuthorizationPolicy propagated after $((attempt * 5)) seconds (HTTP ${POLL_CODE})"
      break
    fi
  else
    STABLE_POLL_COUNT=0
  fi
  if [ "$attempt" -eq 24 ]; then
    echo "FAIL: AuthorizationPolicy did not propagate within 120 seconds"
    exit 1
  fi
  sleep 5
done

# 7a: Without token -- should be rejected
RESPONSE=$(curl -s -w "\n%{http_code}" \
 -H "Host: ${RAW_HOST}" \
 -H "Content-Type: application/json" \
 "http://${KSERVE_INGRESS_HOST_PORT}/v1/models/isvc-sklearn-raw:predict" \
 -d '{"instances": [[6.8, 2.8, 4.8, 1.4]]}')
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 7a raw deployment (no token): HTTP $HTTP_CODE | ${BODY:0:200}"

if [ "$HTTP_CODE" != "403" ] && [ "$HTTP_CODE" != "302" ]; then
  echo "FAIL: Raw deployment: Expected 403/302 without token, got $HTTP_CODE"
  exit 1
fi

# 7b: With valid token -- should succeed
RESPONSE=$(curl -s -w "\n%{http_code}" \
 -H "Authorization: Bearer ${KSERVE_M2M_TOKEN}" \
 -H "Host: ${RAW_HOST}" \
 -H "Content-Type: application/json" \
 "http://${KSERVE_INGRESS_HOST_PORT}/v1/models/isvc-sklearn-raw:predict" \
 -d '{"instances": [[6.8, 2.8, 4.8, 1.4], [6.0, 3.4, 4.5, 1.6]]}')
BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
echo "Test 7b raw deployment (with token): HTTP $HTTP_CODE | ${BODY:0:200}"

if [ "$HTTP_CODE" != "200" ] && [ "$HTTP_CODE" != "404" ] && [ "$HTTP_CODE" != "503" ]; then
  echo "FAIL: Raw deployment: Expected 200/404/503 with token, got $HTTP_CODE"
  exit 1
fi

kubectl delete inferenceservice isvc-sklearn-raw -n ${NAMESPACE}
kubectl delete authorizationpolicy allow-isvc-sklearn-raw -n ${NAMESPACE}

# ============================================================
# Cleanup
# ============================================================
kill $PORT_FORWARD_PID 2>/dev/null || true
sleep 2
kill -9 $PORT_FORWARD_PID 2>/dev/null || true
wait $PORT_FORWARD_PID 2>/dev/null || true
