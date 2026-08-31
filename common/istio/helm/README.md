# Istio Helm Chart

This chart renders the current Kubeflow Istio Kustomize resources with Helm.
It is intentionally static for the first platform wrapper slice so the rendered
output stays aligned with the generated manifests under `common/istio`.

## Installation

Install the foundation charts first, then install Istio in two steps because
Istio custom resources cannot be created until the Istio CRDs exist. The
foundation commands below assume the foundation chart PR is present in the
checkout or has already merged.

```bash
helm install kubeflow-namespaces ./common/kubeflow-namespace/helm --namespace default
helm install kubeflow-platform ./common/kubeflow-roles/helm --namespace kubeflow-system

helm install istio ./common/istio/helm \
  --namespace istio-system \
  --values ./common/istio/helm/ci/values-crds.yaml \
  --wait

helm upgrade istio ./common/istio/helm \
  --namespace istio-system \
  --values ./common/istio/helm/ci/values-oauth2-proxy.yaml \
  --wait
```

For GKE, use the tested GKE profile values instead of the default
oauth2-proxy values:

```bash
helm upgrade istio ./common/istio/helm \
  --namespace istio-system \
  --values ./common/istio/helm/ci/values-gke.yaml \
  --wait
```

To install the full managed platform Istio slice, including the cluster-local
gateway and Kubeflow Istio resources, use:

```bash
helm upgrade istio ./common/istio/helm \
  --namespace istio-system \
  --values ./common/istio/helm/ci/values-platform-full.yaml \
  --wait
```

Helm release metadata and Istio workloads are stored in `istio-system`. The
`kubeflow-namespaces` foundation chart creates `Namespace/istio-system` first.
Istio CNI resources still run in `kube-system`.

## Namespace names

Namespace names are fixed to match the Kustomize baseline and `kubeflow-namespaces` foundation chart. Istio workloads use `istio-system`, Istio CNI resources use `kube-system`, and Kubeflow gateway resources refer to `kubeflow`. These names are not configurable.

## Kustomize Mapping

- `ci/values-crds.yaml`: `common/istio/istio-crds/base`
- `ci/values-base.yaml`: `common/istio/istio-crds/base`, `common/istio/istio-namespace/base` NetworkPolicies, and `common/istio/istio-install/base`
- `ci/values-oauth2-proxy.yaml`: `common/istio/istio-crds/base`, `common/istio/istio-namespace/base` NetworkPolicies, and `common/istio/istio-install/overlays/oauth2-proxy`
- `ci/values-gke.yaml`: `common/istio/istio-crds/base`, `common/istio/istio-namespace/base` NetworkPolicies, and `common/istio/istio-install/overlays/gke`
- `ci/values-cluster-local-gateway.yaml`: `common/istio/cluster-local-gateway/base`
- `ci/values-kubeflow-istio-resources.yaml`: `common/istio/kubeflow-istio-resources/base`
- `ci/values-platform-full.yaml`: the managed platform Istio slice above plus cluster-local gateway and Kubeflow Istio resources

Ambient, insecure, and `cluster-local-gateway/overlays/m2m-auth` variants are
intentionally deferred to later chart slices.

## Regenerate Static Manifests

Run from the repository root:

```bash
KUBEFLOW_SYNCHRONIZE_NO_COMMIT=true ./scripts/synchronize-istio-manifests.sh
```

The synchronization script regenerates the Kustomize manifests and every Helm
static payload together, including provenance headers and formatting cleanup.

## Comparison

```bash
helm lint common/istio/helm
python3 tests/run_helm_kustomize_comparison.py istio crds
python3 tests/run_helm_kustomize_comparison.py istio base
python3 tests/run_helm_kustomize_comparison.py istio oauth2-proxy
python3 tests/run_helm_kustomize_comparison.py istio gke
python3 tests/run_helm_kustomize_comparison.py istio cluster-local-gateway
python3 tests/run_helm_kustomize_comparison.py istio kubeflow-istio-resources
python3 tests/run_helm_kustomize_comparison.py istio platform-full
```

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../tests/README.md).

