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

Helm release metadata is stored in `kubeflow-system`. Istio workloads still run
in `istio-system`, and Istio CNI resources still run in `kube-system`.

## Kustomize Mapping

- `ci/values-crds.yaml`: `common/istio/istio-crds/base`
- `ci/values-base.yaml`: `common/istio/istio-crds/base`, `common/istio/istio-namespace/base`, and `common/istio/istio-install/base`
- `ci/values-oauth2-proxy.yaml`: `common/istio/istio-crds/base`, `common/istio/istio-namespace/base`, and `common/istio/istio-install/overlays/oauth2-proxy`

`cluster-local-gateway`, `kubeflow-istio-resources`, GKE, and ambient overlays
are intentionally deferred to later chart slices.

## Comparison

```bash
helm lint experimental/helm/charts/istio
./tests/helm_kustomize_compare.sh istio crds
./tests/helm_kustomize_compare.sh istio base
./tests/helm_kustomize_compare.sh istio oauth2-proxy
```
