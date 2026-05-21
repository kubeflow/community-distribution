# Istio Helm Chart

This chart renders the current Kubeflow Istio Kustomize resources with Helm.
It is intentionally static for the first platform wrapper slice so the rendered
output stays aligned with the generated manifests under `common/istio`.

## Install

Install the foundation charts first, then install Istio in two steps because
Istio custom resources cannot be created until the Istio CRDs exist. The
foundation commands below assume the foundation chart PR is present in the
checkout or has already merged.

```bash
helm install kubeflow-namespaces ./experimental/helm/charts/kubeflow-namespaces --namespace default
helm install kubeflow-platform ./experimental/helm/charts/kubeflow-platform --namespace kubeflow-system

helm install istio ./experimental/helm/charts/istio \
  --namespace kubeflow-system \
  --values ./experimental/helm/charts/istio/ci/values-crds.yaml \
  --wait

helm upgrade istio ./experimental/helm/charts/istio \
  --namespace kubeflow-system \
  --values ./experimental/helm/charts/istio/ci/values-oauth2-proxy.yaml \
  --wait
```

To install the full managed platform Istio slice, including the cluster-local
gateway and Kubeflow Istio resources, use:

```bash
helm upgrade istio ./experimental/helm/charts/istio \
  --namespace kubeflow-system \
  --values ./experimental/helm/charts/istio/ci/values-platform-full.yaml \
  --wait
```

Helm release metadata is stored in `kubeflow-system`. Istio workloads still run
in `istio-system`, and Istio CNI resources still run in `kube-system`.

## Kustomize Mapping

- `ci/values-crds.yaml`: `common/istio/istio-crds/base`
- `ci/values-base.yaml`: `common/istio/istio-crds/base`, `common/istio/istio-namespace/base`, and `common/istio/istio-install/base`
- `ci/values-oauth2-proxy.yaml`: `common/istio/istio-crds/base`, `common/istio/istio-namespace/base`, and `common/istio/istio-install/overlays/oauth2-proxy`
- `ci/values-cluster-local-gateway.yaml`: `common/istio/cluster-local-gateway/base`
- `ci/values-kubeflow-istio-resources.yaml`: `common/istio/kubeflow-istio-resources/base`
- `ci/values-platform-full.yaml`: the managed platform Istio slice above plus cluster-local gateway and Kubeflow Istio resources

GKE, ambient, insecure, and `cluster-local-gateway/overlays/m2m-auth` variants
are intentionally deferred to later chart slices.

## Regenerate Static Manifests

Run from the repository root:

```bash
kustomize build common/istio/istio-crds/base \
  > experimental/helm/charts/istio/manifests/crds.yaml
kustomize build common/istio/istio-install/base \
  > experimental/helm/charts/istio/manifests/install-base.yaml
kustomize build common/istio/istio-install/overlays/oauth2-proxy \
  > experimental/helm/charts/istio/manifests/install-oauth2-proxy.yaml
kustomize build common/istio/cluster-local-gateway/base \
  > experimental/helm/charts/istio/manifests/cluster-local-gateway.yaml
kustomize build common/istio/kubeflow-istio-resources/base \
  > experimental/helm/charts/istio/manifests/kubeflow-istio-resources.yaml
kustomize build common/istio/istio-namespace/base > /tmp/istio-namespace-build.yaml
awk 'BEGIN{doc=0} /^---$/{doc++; next} doc==0{print}' /tmp/istio-namespace-build.yaml \
  > experimental/helm/charts/istio/manifests/namespace.yaml
awk 'BEGIN{doc=0} /^---$/{doc++; if (doc > 1) print "---"; next} doc>0{print}' /tmp/istio-namespace-build.yaml \
  > experimental/helm/charts/istio/manifests/networkpolicies.yaml
```

## Comparison

```bash
helm lint experimental/helm/charts/istio
./tests/helm_kustomize_compare.sh istio crds
./tests/helm_kustomize_compare.sh istio base
./tests/helm_kustomize_compare.sh istio oauth2-proxy
./tests/helm_kustomize_compare.sh istio cluster-local-gateway
./tests/helm_kustomize_compare.sh istio kubeflow-istio-resources
./tests/helm_kustomize_compare.sh istio platform-full
```
