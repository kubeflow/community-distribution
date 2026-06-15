# OAuth2-Proxy Helm Chart

This chart renders the current Kubeflow oauth2-proxy Kustomize resources with
Helm. It is intentionally static for the first chart slice so rendered output
stays aligned with `common/oauth2-proxy`.

## Install

Install foundation, cert-manager, and Istio first. The `kubeflow-namespaces`
foundation chart creates `Namespace/oauth2-proxy`; this chart stores Helm
release metadata in that same workload namespace.

## Namespace names

Namespace names are fixed to match the Kustomize baseline and `kubeflow-namespaces` foundation chart. oauth2-proxy workloads use `oauth2-proxy`, Istio auth resources use `istio-system`, and gateway references use `kubeflow`. These names are not configurable.

```bash
helm install oauth2-proxy ./common/oauth2-proxy/helm \
  --namespace oauth2-proxy \
  --values ./common/oauth2-proxy/helm/ci/values-m2m-dex-only.yaml
```

For kind-like clusters that use Kubernetes service account JWTs for gateway
machine-to-machine auth, use:

```bash
helm install oauth2-proxy ./common/oauth2-proxy/helm \
  --namespace oauth2-proxy \
  --values ./common/oauth2-proxy/helm/ci/values-m2m-dex-and-kind.yaml
```

## Kustomize Mapping

- `ci/values-base.yaml`: `common/oauth2-proxy/base`
- `ci/values-m2m-dex-only.yaml`: `common/oauth2-proxy/overlays/m2m-dex-only`
- `ci/values-m2m-dex-and-kind.yaml`: `common/oauth2-proxy/overlays/m2m-dex-and-kind`
- `ci/values-m2m-dex-and-eks.yaml`: `common/oauth2-proxy/overlays/m2m-dex-and-eks`

Direct enterprise IdP mode, Cloudflare cache policies, and an upstream
oauth2-proxy Helm dependency wrapper are deferred until the parity chart is
stable.

## Comparison

```bash
helm lint common/oauth2-proxy/helm
./tests/helm_kustomize_compare.sh oauth2-proxy base
./tests/helm_kustomize_compare.sh oauth2-proxy m2m-dex-only
./tests/helm_kustomize_compare.sh oauth2-proxy m2m-dex-and-kind
./tests/helm_kustomize_compare.sh oauth2-proxy m2m-dex-and-eks
```
