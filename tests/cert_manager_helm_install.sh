#!/usr/bin/env bash
# Helm counterpart of tests/cert_manager_install.sh: install the base profile,
# wait for the webhook, then upgrade to the kubeflow profile, mirroring the
# base-then-overlay order of the Kustomize script.
set -euxo pipefail
echo "Installing cert-manager with Helm ..."
helm repo add jetstack https://charts.jetstack.io || helm repo update jetstack
helm dependency build common/cert-manager/helm
helm install cert-manager common/cert-manager/helm \
  --namespace cert-manager \
  --values common/cert-manager/helm/ci/values-base.yaml \
  --wait --timeout 5m
helm upgrade cert-manager common/cert-manager/helm \
  --namespace cert-manager \
  --values common/cert-manager/helm/ci/values-kubeflow.yaml \
  --wait --timeout 5m
kubectl wait --for=jsonpath='{.subsets[0].addresses[0].targetRef.kind}'=Pod endpoints -l 'app in (cert-manager,webhook)' --timeout=180s -n cert-manager
