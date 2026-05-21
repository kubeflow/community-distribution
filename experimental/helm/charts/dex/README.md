# Dex Helm Chart

This chart renders the current Kubeflow Dex Kustomize resources with Helm. It is
intentionally static for the first chart slice so rendered output stays aligned
with `common/dex`.

## Install

Install foundation, cert-manager, Istio, and oauth2-proxy first. Store Helm
release metadata in `kubeflow-system`; Dex workloads still run in `auth`.

```bash
helm install dex ./experimental/helm/charts/dex \
  --namespace kubeflow-system \
  --values ./experimental/helm/charts/dex/ci/values-oauth2-proxy.yaml \
  --wait
```

## Caveats

The default static user, OIDC client secret, and password hash match the current
Kustomize manifests for parity. They are not production credential guidance.

The Dex `AuthCode` CRD is installed from the chart `crds/` directory. Helm
installs CRDs before templates, but CRDs have special upgrade and deletion
lifecycle behavior.

## Kustomize Mapping

- `ci/values-base.yaml`: `common/dex/base`
- `ci/values-istio.yaml`: `common/dex/overlays/istio`
- `ci/values-oauth2-proxy.yaml`: `common/dex/overlays/oauth2-proxy`

Direct Keycloak, Azure, and other enterprise connector profiles are deferred
until the default Dex + oauth2-proxy path is stable.

## Comparison

```bash
helm lint experimental/helm/charts/dex
./tests/helm_kustomize_compare.sh dex base
./tests/helm_kustomize_compare.sh dex istio
./tests/helm_kustomize_compare.sh dex oauth2-proxy
```
