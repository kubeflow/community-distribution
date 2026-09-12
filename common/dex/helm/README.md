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
needed to match the current Kustomize manifests. Chart defaults use placeholders
and are not production credential guidance.

## CustomResourceDefinition lifecycle

Dex stores temporary OAuth authorization codes in Kubernetes through
`authcodes.dex.coreos.com`. This chart renders that CustomResourceDefinition from
`templates/crds.yaml`, carrying `helm.sh/resource-policy: keep`. It is controlled
by `crds.enabled`, which defaults to `true`.

**This deliberately deviates from Helm's published recommendation**, which is to
place CustomResourceDefinitions in a chart `crds/` directory. Helm's own
documentation states that there is *"no support at this time for upgrading or
deleting CRDs using Helm"*
([CRD best practices](https://helm.sh/docs/chart_best_practices/custom_resource_definitions/)),
so a resource in `crds/` keeps its first-install schema forever and is invisible
to both `helm template` and `--dry-run`. Rendering from `templates/` means
`helm upgrade` updates the schema, while `helm.sh/resource-policy: keep` stops
`helm uninstall` from removing the definition and the `AuthCode` objects with it.

Set `crds.enabled=false` when a cluster administrator manages
CustomResourceDefinitions separately.

`templates/crds.yaml` is hand-written rather than copied from upstream, because a
copied file cannot carry the retention annotation. It is kept honest by
`tests/dex_helm_crd_lifecycle_test.py`, which fails when it drifts from the
upstream definition synchronized into `common/dex/base/upstream/crds.yaml`.
`scripts/synchronize-dex-manifests.sh` runs the same check, so an upstream change
that alters the definition fails the synchronization run rather than passing
silently.

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

