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

## Authentication

Out of the box Dex authenticates against a **static password database** holding
one account. That is a demonstration login, not something to run a cluster on.

Replacing it is a values change. Add a connector for the identity provider and
turn the password database off:

```yaml
config:
  enablePasswordDB: false
  connectors:
  - type: oidc
    id: keycloak
    name: Keycloak
    config:
      issuer: https://keycloak.example.com/realms/kubeflow
      clientID: $KEYCLOAK_CLIENT_ID
      clientSecret: $KEYCLOAK_CLIENT_SECRET
      redirectURI: https://kubeflow.example.com/dex/callback
      userNameKey: email
      scopes:
      - openid
      - profile
      - email

extraEnvironmentSecrets:
- keycloak-oidc-credentials
```

Each entry under `config.connectors` is passed to Dex exactly as written, so any
connector the [Dex documentation](https://dexidp.io/docs/connectors/) describes
works — OIDC, LDAP, GitHub, Microsoft, SAML. Only `type`, `id` and `name` are
required by this chart; everything under `config` belongs to Dex.

**Credentials do not belong in `values.yaml`.** Dex substitutes `$VARIABLE`
references from its environment, so put the secret material in a Secret in the
`auth` namespace and name that Secret in `extraEnvironmentSecrets`:

```bash
kubectl create secret generic keycloak-oidc-credentials \
  --namespace auth \
  --from-literal=KEYCLOAK_CLIENT_ID=kubeflow \
  --from-literal=KEYCLOAK_CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET:?set the client secret in the environment first}"
```

The chart does not create these Secrets. They must exist before the release is
installed. Dex reads them into its environment when the process starts, and
updating a Secret does not change the pod template, so after rotating a
credential restart Dex:

```bash
kubectl -n auth rollout restart deployment/dex
```

### Providers behind a private certificate authority

Dex's OIDC connector reads certificate authorities from **files**
(`rootCAs` is a list of paths), so a Secret alone is not enough — it has to be
mounted. `connectorCertificateAuthoritySecret` mounts one read-only at
`/etc/dex/certificate-authorities`:

```yaml
connectorCertificateAuthoritySecret: corporate-certificate-authority
config:
  connectors:
  - type: oidc
    id: keycloak
    name: Keycloak
    config:
      issuer: https://keycloak.example.com/realms/kubeflow
      rootCAs:
      - /etc/dex/certificate-authorities/ca.crt
```

Without this the only way to reach such a provider is `insecureSkipVerify: true`,
which disables certificate verification altogether. Prefer the certificate.

Dex reads these files at start-up, so rotating the certificate authority needs a
restart:

```bash
kubectl -n auth rollout restart deployment/dex
```

The LDAP connector is different: it accepts the certificate inline through
`rootCAData` and needs no mount.

Three guards apply:

- `config.enablePasswordDB: false` with no connector is rejected, because Dex
  would start with no way to authenticate anyone;
- a connector missing `type`, `id` or `name` is rejected before rendering;
- a `rootCAs` path under `/etc/dex/certificate-authorities` with no
  `connectorCertificateAuthoritySecret` set is rejected, because nothing would be
  mounted there.

Changing a connector changes the configuration checksum on the Dex Deployment, so
`helm upgrade` restarts the pods and the new configuration takes effect.

Leaving `config.connectors` empty renders exactly the Kustomize baseline.

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
so a resource in `crds/` retains the schema from its first installation indefinitely; `helm template`
renders it only when `--include-crds` is passed, and `--dry-run` never validates
it. Rendering from `templates/` means
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

Only this scenario is compared against Kustomize, because it is the only one the
Kustomize baseline renders. Connector configurations have no Kustomize
counterpart to compare against; they are covered by
`tests/dex_helm_connectors_test.py` instead.

## Comparison

```bash
helm lint common/dex/helm --namespace auth --values common/dex/helm/ci/values-oauth2-proxy.yaml
python3 tests/run_helm_kustomize_comparison.py dex oauth2-proxy
```

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../tests/README.md).
