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

The chart refuses to render outside `istio-system`.

### Who owns `Namespace/istio-system`

A Kubernetes resource belongs to exactly one Helm release, so exactly one chart
may render the namespace. `namespaces.create` selects which.

| installation | `namespaces.create` | `--create-namespace` |
| --- | --- | --- |
| with the `kubeflow-namespaces` foundation chart, the default | `false` | **never pass it** |
| standalone, without the foundation chart | `true` | required |

**With the foundation chart, do not pass `--create-namespace`.** Measured against
Helm 4.1.0: it replaces the existing namespace with a minimal one and removes
every label the foundation chart applied, including
`pod-security.kubernetes.io/enforce: restricted`. Helm 4 defaults `--server-side`
to `true`, so this happens on a plain `helm install --create-namespace` with no
other flags. See [helm/helm#31767](https://github.com/helm/helm/issues/31767).
Restore the labels with:

```bash
helm upgrade kubeflow-namespaces ./common/kubeflow-namespace/helm --namespace default
```

Setting `namespaces.create=true` while the foundation chart owns the namespace
fails the installation with `invalid ownership metadata`, before anything is
applied.

Do not pass `--take-ownership` in either case. It lets this release adopt a
namespace another release still lists as its own, and uninstalling this release
then deletes the namespace along with everything inside it.

### Installing without the foundation chart

`namespaces.create=true` renders `Namespace/istio-system` from this chart, with
the labels the Kustomize baseline defines. `--create-namespace` is required as
well, because Helm stores the release in `istio-system` before it applies any
resource. Helm creates a bare namespace first and the chart's own namespace is
applied over it, so the labels end up correct.

```bash
helm install istio ./common/istio/helm \
  --namespace istio-system \
  --create-namespace \
  --values ./common/istio/helm/ci/values-crds.yaml \
  --set namespaces.create=true \
  --wait
```

**Repeat `--set namespaces.create=true` on every later `helm upgrade`.** The
profile values files do not set it, so an upgrade that omits the flag resets
the value to its `false` default and removes `Namespace/istio-system` from the
release — deleting the namespace and everything inside it.

## Namespace names

Namespace names are fixed to match the Kustomize baseline and `kubeflow-namespaces` foundation chart. Istio workloads use `istio-system`, Istio CNI resources use `kube-system`, and Kubeflow gateway resources refer to `kubeflow`. These names are not configurable.

## Kustomize Mapping

- `ci/values-crds.yaml`: `common/istio/istio-crds/base`
- `ci/values-base.yaml`: `common/istio/istio-crds/base`, `common/istio/istio-namespace/base`, and `common/istio/istio-install/base`
- `ci/values-oauth2-proxy.yaml`: `common/istio/istio-crds/base`, `common/istio/istio-namespace/base`, and `common/istio/istio-install/overlays/oauth2-proxy`
- `ci/values-gke.yaml`: `common/istio/istio-crds/base`, `common/istio/istio-namespace/base`, and `common/istio/istio-install/overlays/gke`
- `ci/values-cluster-local-gateway.yaml`: `common/istio/cluster-local-gateway/base`
- `ci/values-kubeflow-istio-resources.yaml`: `common/istio/kubeflow-istio-resources/base`
- `ci/values-platform-full.yaml`: the managed platform Istio slice above plus the cluster-local gateway with machine-to-machine authentication (`common/istio/cluster-local-gateway/overlays/m2m-auth`) and Kubeflow Istio resources

`common/istio/istio-namespace/base` renders both the namespace and the
NetworkPolicies. The synchronization script writes them to separate payloads,
`manifests/namespaces.yaml` and `manifests/networkpolicies.yaml`, so each has its
own value. The comparison script enables `namespaces.create` for the scenarios
that build that path, so the namespace is compared rather than skipped.

`clusterLocalGateway.machineToMachineAuthentication.enabled` selects the
`cluster-local-gateway/overlays/m2m-auth` payload instead of the base payload:
the gateway then requires valid JWT principals, matching what the managed
platform installs. Ambient and insecure variants remain intentionally deferred
to later chart slices.

## Regenerate Static Manifests

Run from the repository root:

```bash
KUBEFLOW_SYNCHRONIZE_NO_COMMIT=true ./scripts/synchronize-istio-manifests.sh
```

The synchronization script regenerates the Kustomize manifests and every Helm
static payload together, including provenance headers and formatting cleanup.

## Comparison

```bash
# The chart guards its namespace, so lint from istio-system. Linting elsewhere
# stops at the guard and reports success without checking any template.
helm lint common/istio/helm --namespace istio-system
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

