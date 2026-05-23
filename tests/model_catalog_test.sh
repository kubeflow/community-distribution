#!/bin/bash
set -euxo pipefail


if ! kubectl get deployment/model-catalog-server -n kubeflow-user-example-com; then
    echo "ERROR: Model Catalog deployment not found"
    exit 1
fi

if ! kubectl get svc/model-catalog -n kubeflow-user-example-com; then
    echo "ERROR: Model Catalog service not found"
    exit 1
fi

kubectl get pods -n kubeflow-user-example-com -l app.kubernetes.io/name=model-catalog,app.kubernetes.io/component=server

nohup kubectl port-forward svc/model-catalog -n kubeflow-user-example-com 8082:8080 &
PORT_FORWARD_PID=$!

MAX_RETRIES=30
RETRY_COUNT=0
while ! curl -s localhost:8082 > /dev/null; do
    echo "Waiting for port-forwarding to be ready... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 1
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "ERROR: Port-forwarding failed to become ready"
        kill $PORT_FORWARD_PID 2>/dev/null 
        exit 1
    fi
done
echo "Port-forwarding ready!"

echo "Testing Model Catalog API..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8082/api/model_catalog/v1alpha1/models")

if [ "$HTTP_CODE" -eq 200 ] || [ "$HTTP_CODE" -eq 404 ]; then
    echo "Model Catalog API is responding (HTTP $HTTP_CODE)"
else
    echo "ERROR: Model Catalog API returned unexpected status code: $HTTP_CODE"
    kill $PORT_FORWARD_PID 2>/dev/null 
    exit 1
fi

kill $PORT_FORWARD_PID 2>/dev/null 


