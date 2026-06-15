# Dex Helm Chart

This chart renders the current Kubeflow Dex Kustomize resources with Helm. It is
intentionally static for the first chart slice so rendered output stays aligned
with `common/dex`.

## Install

Install foundation, cert-manager, Istio, and oauth2-proxy first. The
`kubeflow-namespaces` foundation chart creates `Namespace/auth`; this chart
stores Helm release metadata in that same workload namespace.

## Namespace names

Namespace names are fixed to match the Kustomize baseline and `kubeflow-namespaces` foundation chart. Dex workloads use `auth`, Istio gateway references use `kubeflow` and `istio-system`, and oauth2-proxy references use `oauth2-proxy`. These names are not configurable.

```bash
helm install dex ./common/dex/helm \
  --namespace auth \
  --values ./common/dex/helm/ci/values-oauth2-proxy.yaml \
  --wait
```

## Caveats

The CI values contain the static user, OIDC client secret, and password hash
needed to match the current Kustomize manifests. Chart defaults use placeholders
and are not production credential guidance.

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
helm lint common/dex/helm
./tests/helm_kustomize_compare.sh dex base
./tests/helm_kustomize_compare.sh dex istio
./tests/helm_kustomize_compare.sh dex oauth2-proxy
```
