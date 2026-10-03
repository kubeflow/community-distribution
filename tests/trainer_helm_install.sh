#!/usr/bin/env bash
# Install the API, control-plane and default-catalog releases in that order.
#
# Without arguments all three releases are installed; this is the workflow call.
# Arguments name the releases to install (trainer-apis, trainer,
# trainer-runtimes). The named releases are installed in the same order and with
# the same readiness sequence as in a complete installation, so the reinstall
# paths of tests/trainer_helm_lifecycle_test.sh call this script instead of
# repeating its commands.
#
# TRAINER_APIS_CHART, when set, is the chart of the trainer-apis release instead
# of the directory applications/trainer/helm-crds: a packaged parent or another
# chart path. A relative path is resolved against the calling directory. The
# other two releases and the order are unaffected.
#
#   helm package applications/trainer/helm-crds --destination /path/to/packages
#   TRAINER_APIS_CHART=/path/to/packages/trainer-apis-0.1.0.tgz ./tests/trainer_helm_install.sh
set -euxo pipefail

if [[ -n "${TRAINER_APIS_CHART:-}" ]]; then
  if [[ ! -e "$TRAINER_APIS_CHART" ]]; then
    echo "ERROR: TRAINER_APIS_CHART names ${TRAINER_APIS_CHART}, which does not exist." >&2
    exit 1
  fi
  TRAINER_APIS_CHART=$(realpath "$TRAINER_APIS_CHART")
fi

SELECTED_RELEASES=("$@")
if [[ $# -eq 0 ]]; then
  SELECTED_RELEASES=(trainer-apis trainer trainer-runtimes)
fi
for release in "${SELECTED_RELEASES[@]}"; do
  case "$release" in
  trainer-apis | trainer | trainer-runtimes) ;;
  *)
    echo "ERROR: ${release} is not one of trainer-apis, trainer and trainer-runtimes." >&2
    exit 1
    ;;
  esac
done

REPOSITORY_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPOSITORY_ROOT"
source scripts/library.sh
require_helm_major_version 4
TRAINER_APIS_CHART=${TRAINER_APIS_CHART:-applications/trainer/helm-crds}

release_is_selected() {
  local release
  for release in "${SELECTED_RELEASES[@]}"; do
    if [[ "$release" == "$1" ]]; then
      return 0
    fi
  done
  return 1
}

install_api_release() {
  local definition
  helm install trainer-apis "$TRAINER_APIS_CHART" \
    --namespace kubeflow-system --wait --timeout 5m
  for definition in \
    clustertrainingruntimes.trainer.kubeflow.org \
    trainingruntimes.trainer.kubeflow.org \
    trainjobs.trainer.kubeflow.org \
    jobsets.jobset.x-k8s.io; do
    kubectl wait --for=condition=Established "crd/${definition}" --timeout=120s
  done
}

install_control_plane_release() {
  local deployment webhook service
  helm install trainer applications/trainer/helm \
    --namespace kubeflow-system --wait --timeout 10m
  for deployment in kubeflow-trainer-controller-manager jobset-controller-manager; do
    kubectl rollout status "deployment/${deployment}" \
      --namespace kubeflow-system --timeout=300s
  done

  # Preserve the established installer workaround until live testing establishes
  # that the JobSet controller no longer needs to reload its serving certificate.
  kubectl rollout restart deployment/jobset-controller-manager --namespace kubeflow-system
  kubectl rollout status deployment/jobset-controller-manager \
    --namespace kubeflow-system --timeout=300s

  for webhook in \
    mutatingwebhookconfiguration/defaulter.trainer.kubeflow.org \
    mutatingwebhookconfiguration/jobset-mutating-webhook-configuration \
    validatingwebhookconfiguration/validator.trainer.kubeflow.org \
    validatingwebhookconfiguration/jobset-validating-webhook-configuration; do
    kubectl wait "$webhook" --timeout=120s \
      --for='jsonpath={.webhooks[0].clientConfig.caBundle}'
  done
  for service in kubeflow-trainer-controller-manager jobset-webhook-service; do
    kubectl wait "endpoints/${service}" --namespace kubeflow-system \
      --for='jsonpath={.subsets[0].addresses[0].ip}' --timeout=120s
  done
}

install_catalog_release() {
  helm install trainer-runtimes applications/trainer/helm-runtimes \
    --namespace kubeflow-system --wait --timeout 5m
  kubectl get clustertrainingruntimes
}

# The foundation release owns this shared namespace; Trainer never creates it.
kubectl get namespace kubeflow-system
if release_is_selected trainer-apis; then
  install_api_release
fi
if release_is_selected trainer; then
  install_control_plane_release
fi
if release_is_selected trainer-runtimes; then
  install_catalog_release
fi
