#!/bin/bash
set -euxo pipefail

cd applications/katib/upstream && kustomize build installs/katib-with-kubeflow | kubectl apply -f - && cd ../../../

if ! kubectl get deployment katib-controller -n kubeflow -o yaml | grep -q -- "--inject-security-context=true"; then
  kubectl patch deployment katib-controller -n kubeflow --type=json -p='[
    {
      "op": "add",
      "path": "/spec/template/spec/containers/0/args/-",
      "value": "--inject-security-context=true"
    }
  ]'
fi

kubectl wait --for=condition=Available deployment/katib-controller -n kubeflow --timeout=300s

kubectl wait --for=condition=Available deployment/katib-mysql -n kubeflow --timeout=300s

kubectl label namespace $KF_PROFILE katib.kubeflow.org/metrics-collector-injection=enabled --overwrite
