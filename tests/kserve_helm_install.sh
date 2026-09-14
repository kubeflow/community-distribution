#!/usr/bin/env bash
# Helm counterpart of tests/kserve_install.sh, proven equivalent to
# applications/kserve/kserve by the kserve platform comparison scenario.
#
# Two release revisions replace the raw installer's apply-fail-apply dance:
# the first renders only the custom resource definitions, the second adds the
# control plane once every definition is established, because the cluster
# serving runtimes and the cluster storage container in the payload cannot be
# created before their definitions exist.
set -euxo pipefail
echo "Installing KServe with Helm ..."
helm install kserve applications/kserve/kserve/helm \
  --namespace kserve \
  --values applications/kserve/kserve/helm/ci/values-platform.yaml \
  --set resources.enabled=false \
  --wait --timeout 5m

mapfile -t CUSTOM_RESOURCE_DEFINITION_NAMES < <(
  helm get manifest kserve --namespace kserve |
    awk '
      $0 == "kind: CustomResourceDefinition" {
        custom_resource_definition = 1
        next
      }
      custom_resource_definition && /^  name: / {
        print $2
        custom_resource_definition = 0
      }
    '
)
if [[ "${#CUSTOM_RESOURCE_DEFINITION_NAMES[@]}" -eq 0 ]]; then
  echo "No CustomResourceDefinition resources were found in the kserve Helm release." >&2
  exit 1
fi
for name in "${CUSTOM_RESOURCE_DEFINITION_NAMES[@]}"; do
  kubectl wait --for=condition=Established "crd/${name}" --timeout=120s
done

helm upgrade kserve applications/kserve/kserve/helm \
  --namespace kserve \
  --values applications/kserve/kserve/helm/ci/values-platform.yaml \
  --wait --timeout 10m

kubectl wait --for=condition=Ready -n kserve --timeout=120s \
  certificate/serving-cert \
  certificate/llmisvc-serving-cert \
  certificate/localmodel-serving-cert
kubectl wait --for=create -n kserve --timeout=60s \
  secret/kserve-webhook-server-cert \
  secret/llmisvc-webhook-server-cert \
  secret/localmodel-webhook-server-cert

mapfile -t DEPLOYMENT_NAMES < <(
  helm get manifest kserve --namespace kserve |
    awk '
      $0 == "kind: Deployment" {
        deployment = 1
        next
      }
      deployment && /^  name: / {
        print $2
        deployment = 0
      }
    '
)
if [[ "${#DEPLOYMENT_NAMES[@]}" -eq 0 ]]; then
  echo "No Deployment resources were found in the kserve Helm release." >&2
  exit 1
fi
for name in "${DEPLOYMENT_NAMES[@]}"; do
  kubectl rollout status "deployment/${name}" -n kserve --timeout=300s
done

# The Models Web Application keeps its Kustomize installation until its own
# chart lands; it joins this script in that pull request.
kustomize build applications/kserve/kserve-ui | kubectl apply --server-side --force-conflicts -f -
kubectl wait --for=condition=Available -n kserve --timeout=300s \
  deployment/kserve-models-web-application
