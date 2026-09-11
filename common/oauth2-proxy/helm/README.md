# OAuth2-Proxy Helm Chart

This chart renders the current Kubeflow oauth2-proxy Kustomize resources with
Helm. It is intentionally static for the first chart slice so rendered output
stays aligned with `common/oauth2-proxy`.

## Installation

Install foundation and cert-manager first. Install Istio through
`common/istio/istio-install/overlays/oauth2-proxy` so its mesh configuration
defines the `oauth2-proxy` extension provider. Install Dex through
`common/dex/overlays/oauth2-proxy` for the login flow configured by this chart.
The `kubeflow-namespaces` foundation chart creates
`Namespace/oauth2-proxy`; this chart stores Helm release metadata in that same
workload namespace.

## Credentials

`credentials.clientSecret` and `credentials.cookieSecret` ship as `REPLACE_ME`
placeholders and **the chart refuses to render while they are in place**. The
cookie secret signs session cookies, so a publicly known value lets anyone forge
a session.

```bash
openssl rand -base64 32 | tr -- '+/' '-_'
```

The cookie secret must be 16, 24 or 32 bytes, either raw or **URL-safe** base64.
oauth2-proxy decodes with unpadded URL-safe base64 and uses the decoded bytes
only when they are a valid key length, falling back to the raw string otherwise.
The chart applies the same rule, so a value containing `+` or `/` is treated as
raw rather than decoded — which is why the command above pipes through `tr`. Any other length is accepted by Kubernetes and
then crash-loops oauth2-proxy, so the chart checks it before rendering.

Nothing is checked when `oauth2Proxy.enabled=false`, since no Secret is
rendered.

Use the same `clientSecret` here and in the `dex` chart, or the OIDC client
credentials will not match.

## Namespace names

Namespace names are fixed to match the Kustomize baseline and `kubeflow-namespaces` foundation chart. oauth2-proxy workloads use `oauth2-proxy`, Istio authentication and authorization resources use `istio-system`, and gateway references use `kubeflow`. These names are not configurable.

Create a user-owned `oauth2-proxy-values.yaml` before installation. Provide
deployment-specific `credentials.clientSecret`, `credentials.cookieSecret`,
and machine-to-machine issuer settings. When `clusterJwksProxy.enabled` is
true, provide a pinned `clusterJwksProxy.image` tag or digest. The values under
`ci/` are comparison fixtures and must not be used as deployment credentials.

```bash
helm install oauth2-proxy ./common/oauth2-proxy/helm \
  --namespace oauth2-proxy \
  --values ./oauth2-proxy-values.yaml
```

## Kustomize Mapping

- `ci/values-m2m-dex-and-kind.yaml`: `common/oauth2-proxy/overlays/m2m-dex-and-kind`

Amazon EKS machine-to-machine values are deferred until Helm integration tests
or documented cluster-specific scenarios cover them.

Direct enterprise IdP mode, Cloudflare cache policies, and an upstream
oauth2-proxy Helm dependency wrapper are deferred until the parity chart is
stable.

## Comparison

```bash
helm lint common/oauth2-proxy/helm
python3 tests/run_helm_kustomize_comparison.py oauth2-proxy m2m-dex-and-kind
```

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../tests/README.md).

