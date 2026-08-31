#!/bin/bash
set -euxo

NAMESPACE=$1
REPOSITORY_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "${GITHUB_WORKSPACE:-$(pwd)}")
SPARK_APPLICATION_YAML="${REPOSITORY_ROOT}/applications/spark/sparkapplication_example.yaml"

kubectl label namespace $NAMESPACE istio-injection=enabled --overwrite
kubectl get namespaces --selector=istio-injection=enabled
kubectl -n $NAMESPACE apply -f "$SPARK_APPLICATION_YAML"

# Wait for the Spark application
sleep 5
# Wait until the SparkApplication reaches the "RUNNING" state
while true; do
    STATUS=$(kubectl get sparkapplication spark-pi-python -n $NAMESPACE -o jsonpath='{.status.applicationState.state}')
    
    if [ "$STATUS" == "RUNNING" ]; then
        echo "SparkApplication 'spark-pi-python' is running."

        break
    else
        echo "Waiting for SparkApplication to be in RUNNING state. Current state: $STATUS"
        sleep 5  # Check every 5 seconds
    fi
done

# Wait for Spark to be ready.
sleep 5
# Wait until the Spark driver pod reaches the "Succeeded" or "Failed" phase
while true; do
    POD_STATUS=$(kubectl get pod spark-pi-python-driver -n $NAMESPACE -o jsonpath='{.status.phase}')
    
    if [ "$POD_STATUS" == "Succeeded" ] || [ "$POD_STATUS" == "Failed" ]; then
        echo "Driver pod has completed with status: $POD_STATUS"
        break
    else
        echo "Waiting for driver pod to complete. Current status: $POD_STATUS"
        sleep 5  # Check every 5 seconds
    fi
done

kubectl -n $NAMESPACE logs pod/spark-pi-python-driver

# Delete Spark Deployment
kubectl -n $NAMESPACE delete -f "$SPARK_APPLICATION_YAML"


# Verify the aggregated Spark ClusterRoles grant access to SparkConnect resources.
# kubeflow-spark-edit aggregates into kubeflow-edit, which is bound to default-editor.
# Profiles do not create a default-viewer, so bind a dedicated viewer identity here.
EDITOR="system:serviceaccount:${NAMESPACE}:default-editor"
VIEWER_SERVICE_ACCOUNT_NAME="spark-permissions-viewer"
trap 'kubectl -n "$NAMESPACE" delete rolebinding "$VIEWER_SERVICE_ACCOUNT_NAME" --ignore-not-found; kubectl -n "$NAMESPACE" delete serviceaccount "$VIEWER_SERVICE_ACCOUNT_NAME" --ignore-not-found' EXIT
kubectl -n "$NAMESPACE" create serviceaccount "$VIEWER_SERVICE_ACCOUNT_NAME"
kubectl -n "$NAMESPACE" create rolebinding "$VIEWER_SERVICE_ACCOUNT_NAME" \
    --clusterrole=kubeflow-view \
    --serviceaccount="${NAMESPACE}:${VIEWER_SERVICE_ACCOUNT_NAME}"
VIEWER="system:serviceaccount:${NAMESPACE}:${VIEWER_SERVICE_ACCOUNT_NAME}"

for VERB in create delete get list patch update watch; do
    kubectl auth can-i "$VERB" sparkconnects --as="$EDITOR" -n "$NAMESPACE" | grep -qx yes
done

kubectl auth can-i get sparkconnects/status --as="$EDITOR" -n "$NAMESPACE" | grep -qx yes

for VERB in get list watch; do
    kubectl auth can-i "$VERB" sparkconnects --as="$VIEWER" -n "$NAMESPACE" | grep -qx yes
done

kubectl auth can-i get sparkconnects/status --as="$VIEWER" -n "$NAMESPACE" | grep -qx yes

# Viewers must not be able to modify SparkConnect resources.
for VERB in create delete patch update; do
    ! kubectl auth can-i "$VERB" sparkconnects --as="$VIEWER" -n "$NAMESPACE" | grep -qx yes
done

echo "Aggregated Spark ClusterRole permissions for sparkconnects verified."