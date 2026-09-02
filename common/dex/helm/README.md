# Dex Helm Chart

This chart renders the default Kubeflow Dex with oauth2-proxy Kustomize path
with Helm. It is intentionally static for the first chart slice so rendered
output stays aligned with `common/dex/overlays/oauth2-proxy`.

## Installation

Install foundation, cert-manager, Istio, and oauth2-proxy first. The
`kubeflow-namespaces` foundation chart creates `Namespace/auth`; this chart
stores Helm release metadata in that same workload namespace.

Create `dex-values.yaml` with a unique OAuth client secret in
`oidcClient.secret` and a bcrypt password hash in `staticPassword.hash`. Set the
static user fields and optional Istio or NetworkPolicy toggles for the target
environment. Use the same OAuth client secret for Dex and oauth2-proxy so the
OIDC client credentials match.

```bash
helm install dex ./common/dex/helm \
  --namespace auth \
  --values ./dex-values.yaml \
  --wait
```

## Namespace names

Namespace names are fixed to match the Kustomize baseline and `kubeflow-namespaces` foundation chart. Dex workloads use `auth`, Istio gateway references use `kubeflow` and `istio-system`, and oauth2-proxy references use `oauth2-proxy`. These names are not configurable.

## Caveats

The CI values contain the static user, OIDC client secret, and password hash
needed to match the current Kustomize manifests. They are fixtures, not
production credential guidance.

Chart defaults are `REPLACE_ME` placeholders and **the chart refuses to render
while they are in place**. Installing with the defaults would otherwise create a
Secret holding a publicly known OIDC client secret. `staticPassword.hash` is also
checked for the complete bcrypt format, because a truncated hash silently rejects
every password. Neither is checked when `dex.enabled=false`, since no Secret is
rendered.

The Dex `AuthCode` CRD is installed from the chart `crds/` directory. Helm
installs CRDs before templates, but CRDs have special upgrade and deletion
lifecycle behavior.

## Kustomize Mapping

This chart currently validates one meaningful Kubeflow customer scenario:

- `ci/values-oauth2-proxy.yaml`: `common/dex/overlays/oauth2-proxy`

Direct Keycloak, Azure, and other enterprise connector profiles are deferred
until the default Dex + oauth2-proxy path is stable.

## Comparison

```bash
helm lint common/dex/helm --namespace auth
python3 tests/run_helm_kustomize_comparison.py dex oauth2-proxy
```

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../tests/README.md).

