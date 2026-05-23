#!/bin/bash
set -euxo pipefail

(
    cd applications/hub/upstream/options/catalog/base
    kustomize build . | kubectl apply -n kubeflow-user-example-com -f -
)

kubectl wait --for=condition=Available deployment/model-catalog-server -n kubeflow-user-example-com --timeout=120s
