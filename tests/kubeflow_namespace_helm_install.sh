#!/usr/bin/env bash
# Helm counterpart of the "Create Kubeflow Namespace" step: the
# kubeflow-namespaces chart owns every platform namespace and the network
# policies, proven equivalent to common/kubeflow-namespace/base by
# tests/run_helm_kustomize_comparison.py kubeflow-namespaces.
#
# Two phases: the first release revision renders only the Namespace objects,
# the second adds the NetworkPolicies. In one revision Helm pre-creates the
# namespaces its NetworkPolicies reference, and on a fast runner that bare
# namespace wins the race against the chart's own labeled Namespace manifest,
# leaving kubeflow-system without istio-injection and Pod Security labels.
set -euxo pipefail
helm install kubeflow-namespaces common/kubeflow-namespace/helm \
  --namespace default \
  --values common/kubeflow-namespace/helm/ci/values-default.yaml \
  --set networkPolicies.enabled=false \
  --wait --timeout 5m
helm upgrade kubeflow-namespaces common/kubeflow-namespace/helm \
  --namespace default \
  --values common/kubeflow-namespace/helm/ci/values-default.yaml \
  --wait --timeout 5m

# Fail here, not twenty minutes later at the first webhook call, if a
# namespace ever comes up without its labels again.
for namespace in kubeflow kubeflow-system; do
  labels=$(kubectl get namespace "$namespace" -o jsonpath='{.metadata.labels}')
  for label in istio-injection pod-security.kubernetes.io/enforce; do
    echo "$labels" | grep -q "$label" || {
      echo "ERROR: namespace $namespace is missing the $label label: $labels"
      exit 1
    }
  done
done
