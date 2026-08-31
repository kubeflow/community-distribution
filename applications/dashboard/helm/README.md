# Kubeflow Dashboard Helm Chart

This chart renders the current Kubeflow Dashboard Kustomize resources with Helm.
Kustomize remains the source of truth. The synchronization script builds the
platform overlay once and writes deterministic payloads under `manifests/`, which
small templates load with `.Files.Get`. Helm does not evaluate that content as a
template, so Go template delimiters inside upstream manifests are emitted
literally.

The resources that carry a value Kustomize already declares - the three
Deployments and the four ConfigMaps - are rendered from hand-written templates
instead, so those values can be set through `values.yaml`. Everything else is
vendored verbatim. Before committing an update, the synchronization script runs
Helm linting and the Helm/Kustomize parity comparison.

## Installation

Install the platform prerequisites first: `kubeflow-namespaces`,
`kubeflow-platform`, `cert-manager`, `istio`, `oauth2-proxy`, and `dex`.

The chart requires its release namespace to be `kubeflow` and refuses to install
anywhere else. It does not create or own that namespace - the
`kubeflow-namespaces` foundation chart does. Every resource this chart renders
declares `namespace: kubeflow`, so a release installed elsewhere would store its
metadata in one namespace while modifying another, and `helm uninstall` would
then delete resources it does not appear to own.

```bash
helm install kubeflow-dashboard ./applications/dashboard/helm \
  --namespace kubeflow \
  --wait
```

## How this chart is kept up to date

Nobody maintains the generated payloads by hand. They are output, not source.

```text
 upstream Dashboard release
        |
        |  scripts/synchronize-dashboard-manifests.sh
        v
 kustomize build applications/dashboard/helm/kustomize
        |
        |  scripts/generate-dashboard-helm-manifests.py
        v
 manifests/*.yaml        generated, DO NOT EDIT header, never hand-edited
 templates/*.yaml        hand-written, never generated into
```

Three mechanisms keep that honest, and each fails loudly rather than drifting:

- **Regeneration is idempotent.** The idempotence job re-runs the synchronization
  script and fails if the tree changes, so a hand-edited payload is caught.
- **Parity is the drift detector.** Every scenario compares the committed chart
  against a fresh `kustomize build`. If an upstream release changes a resource
  and the chart does not follow, the comparison fails.
- **Excluded resources are declared.** The seven resources rendered from
  hand-written templates are named in `scripts/generate-dashboard-helm-manifests.py`.
  If one stops being produced by Kustomize, the generator refuses to run rather
  than silently dropping it:

  ```text
  hand-written resources are no longer rendered by Kustomize;
  their templates are orphaned: Deployment/dashboard
  ```

So at release *n + 10* the payloads are whatever `kustomize build` produced at
that release, and the only manual surface is those seven templates — each one
checked against Kustomize by the parity job on every run.

Regenerate with:

```bash
python3 -m pip install pyyaml "ruamel.yaml==0.19.1"
KUBEFLOW_SYNCHRONIZE_NO_COMMIT=true \
  ./scripts/synchronize-dashboard-manifests.sh
```

Do not edit files under `manifests/` directly.

Review a generated payload change in two steps, because they prove different
things. First read the change by resource identity and upstream source boundary:
which resources appeared, disappeared or changed, and does each change belong to
the upstream release. Then regenerate and confirm `git diff` is empty. The replay
proves only that the generator is deterministic; it cannot tell you whether a new
upstream release introduced an unintended webhook, permission or policy change.

## Configuration

Every value corresponds to something the Kustomize baseline already declares -
an `images:` transformer or a `configMapGenerator` input - and every default
equals the value rendered by `applications/dashboard/overlays/istio`.

| Value | Default | Purpose |
| --- | --- | --- |
| `image.registry` | `ghcr.io/kubeflow/dashboard` | Registry prefix for all four images. Set this to install from a mirror or an air-gapped registry. |
| `image.tag` | chart `appVersion` | Tag shared by all four images. |
| `centralDashboard.image.repository` | `dashboard` | Central Dashboard repository. |
| `profileController.image.repository` | `profile-controller` | Profile Controller repository. |
| `profileController.accessManagement.image.repository` | `access-management` | Access Management repository. |
| `podDefaultsWebhook.image.repository` | `poddefaults-webhook` | PodDefaults webhook repository. |
| `identity.userIdHeader` | `kubeflow-userid` | Request header carrying the user identity. |
| `identity.userIdPrefix` | empty | Prefix stripped from that header. |
| `centralDashboard.registrationFlow` | `false` | Self-service user registration. |
| `centralDashboard.collectMetrics` | `true` | Anonymous usage metrics. |
| `centralDashboard.links` | inherited | Menu, quick link and documentation definitions, as JSON. |
| `centralDashboard.settings` | inherited | Central Dashboard runtime settings, as JSON. |
| `profileController.admin` | empty | Cluster administrator granted access to every Profile. |
| `profileController.workloadIdentity` | empty | Google Cloud workload identity for Profile service accounts. |
| `profileController.namespaceLabels` | inherited | Labels applied to every Profile namespace, as YAML. |
| `customResourceDefinitions.enabled` | `true` | Render the PodDefault and Profile custom resource definitions. |

The three document values - `links`, `settings` and `namespaceLabels` - are
**strings** containing a whole document. Passing a map or list is rejected,
because Helm would otherwise write Go's own formatting of that value and the
application could not parse it. Leave a document empty to inherit the upstream
default byte for byte, or supply the replacement as a quoted block scalar.

`identity.userIdHeader` and `identity.userIdPrefix` are consumed by both the
Central Dashboard and the Profile Controller. They are declared once and rendered
into both ConfigMaps so the two cannot disagree.

**Authentication is not configured here.** `centralDashboard.registrationFlow`
turns off the self-service user registration screen, which is the only
sign-in-related surface this chart owns. The login flow itself belongs to the
`dex` and `oauth2-proxy` charts; this chart only consumes the identity those
components put in `identity.userIdHeader`.

The three values ending in `Principal` are platform wiring rather than ordinary
settings. They are the service account identities that Kubeflow components
authenticate with when calling the Profile Controller. Changing one without also
changing the corresponding component's namespace or service account breaks
authorization.

A value left empty for `links`, `settings` or `namespaceLabels` inherits the
upstream document from `manifests/documents/` byte for byte. Set it to replace
the document entirely.

Changing any value that feeds a ConfigMap updates a checksum annotation on the
consuming Deployment, so `helm upgrade` restarts the workload. Kustomize hashes
its generated ConfigMap names for the same effect; `dashboard-config` is the
exception and keeps a stable name on both sides.

## Caveats

The platform Dashboard Kustomize overlay includes Central Dashboard, the
PodDefaults webhook, and Profile Controller with KFAM. This chart keeps that
grouping for parity.

### Upgrading

Helm 4 applies server-side. Two sets of fields in this chart are owned by other
controllers once the cluster is running:

- the Kubernetes RBAC aggregation controller fills in `.rules` on the aggregated
  `poddefaults-admin` and `poddefaults-edit` cluster roles, which ship empty;
- cert-manager's CA injector writes
  `.webhooks[].clientConfig.caBundle` on the PodDefaults webhook configuration.

A plain `helm upgrade` therefore stops with a field-ownership conflict. Pass
`--force-conflicts`:

```bash
helm upgrade kubeflow-dashboard ./applications/dashboard/helm \
  --namespace kubeflow --force-conflicts --wait
```

This is safe here: both controllers reconcile continuously and restore their
fields immediately after the apply, which was verified on a live cluster. Note
that an upgrade which fails on a conflict has already applied the objects it
processed before the failure, so re-run it rather than assuming nothing changed.

### Custom resource definition lifecycle

The `profiles.kubeflow.org` and `poddefaults.kubeflow.org` custom resource
definitions are rendered from `templates/` and carry
`helm.sh/resource-policy: keep`. This deviates from Helm's documented
recommendation to place custom resource definitions in `crds/`, deliberately:
Helm never upgrades or deletes anything in `crds/`, which would freeze both
schemas at their first installed version. Rendering them as templates keeps the
schemas upgradeable, while the retention policy stops `helm uninstall` from
deleting every Profile and PodDefault in the cluster.

Because they are templates rather than `crds/` content, Helm's `--skip-crds`
option has no effect on them. Use `customResourceDefinitions.enabled=false` when
an administrator or another release already owns both definitions.

| Operation | Behaviour |
| --- | --- |
| `helm install` | Creates both definitions unless `customResourceDefinitions.enabled=false`. |
| `helm upgrade` | Applies schema changes from the new chart version. |
| `helm uninstall` | **Retains** both definitions and every Profile and PodDefault. Namespaced Dashboard resources are removed. |
| reinstall | Succeeds against the retained definitions and adopts them into the new release. |
| manual cleanup | `kubectl delete crd profiles.kubeflow.org poddefaults.kubeflow.org` — this deletes every Profile and PodDefault in the cluster. |

## Kustomize Mapping

- `ci/values-platform.yaml`: `applications/dashboard/overlays/istio`

## Comparison

```bash
helm lint applications/dashboard/helm --namespace kubeflow
python3 tests/run_helm_kustomize_comparison.py kubeflow-dashboard platform
python3 tests/run_helm_kustomize_comparison.py kubeflow-dashboard --all-scenarios
python3 tests/dashboard_helm_chart_test.py
python3 tests/dashboard_helm_manifest_generator_test.py
```

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../tests/README.md).

