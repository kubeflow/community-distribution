# KServe Helm Chart

This chart renders the current KServe Kustomize component,
`applications/kserve/kserve`, with Helm. Kustomize remains the source of truth.
The synchronization script builds the component once and writes deterministic
payloads under `charts/kserve-payload/manifests/`, which one small template
loads with `.Files.Get`: `platform-resources.yaml` for the control plane and one
file per custom resource definition under `custom-resource-definitions/`,
because the combined definitions exceed Helm's 5 MiB limit for a chart file.

## Packaging

One release installs everything. The `kserve` chart is a thin parent; the
generated payload and the templates that load it are the internal
`kserve-payload` chart, an unpacked directory under `charts/` that the parent
declares as a dependency with the alias `payload` and without a repository.
The source tree therefore holds no `Chart.lock` and no dependency archive, and
no installation step runs `helm dependency build`.

The split exists because of the release record. Helm stores every release
revision as one Kubernetes Secret, which cannot exceed 1,048,576 bytes, and
that record embeds the files of the installed chart but not the files of its
dependencies. With the payload in the parent the record needs about 1.2 MB and
the first `helm install` fails; as a dependency it needs less than half of the
limit. `tests/helm_release_size.py kserve` measures the full installation and
`tests/kserve_helm_release_size_test.py` the first, definitions-only revision.

`kserve-payload` is not installable on its own and is not the upstream KServe
chart.

Helm does not send `.Files.Get` content through the template renderer, so the
Go template expressions that KServe ships in `inferenceservice-config` (the
path-based routing template `/serving/{{ .Namespace }}/{{ .Name }}`) and in
every `ClusterServingRuntime` are emitted literally instead of being resolved
to empty strings.

The payload carries every decision of the Kustomize component: the restricted
Pod Security Standard hardening of the storage initializer, the Istio sidecar
opt-out of the three controllers, the omission of the LocalModel node agent
and of the LLM inference service configuration templates with their validation
webhook, the path-based ingress configuration, the aggregated Kubeflow roles
and the webhook NetworkPolicy.

A resource in the payload keeps the content Kustomize rendered. The generator
departs from that output in four controlled ways and in no other: every custom
resource definition receives `helm.sh/resource-policy: keep`; the definitions
are written one per file; `Namespace/kserve` is left out, because the
`kubeflow-namespaces` chart owns it; and the aggregated `kubeflow-kserve-admin`
cluster role omits its empty `rules` field, because the Kubernetes role
aggregation controller owns that field.

## Prerequisites

| chart | provides |
| --- | --- |
| `kubeflow-namespaces` (`common/kubeflow-namespace/helm`) | `Namespace/kserve` with its Pod Security labels |
| `cert-manager` (`common/cert-manager/helm`) | the webhook certificates |
| `istio` (`common/istio/helm`) and Knative Serving | the ingress and cluster-local gateways the inference service configuration refers to |

The chart requires its release namespace to be `kserve` and refuses to install
anywhere else. It does not create or own that namespace; the
`kubeflow-namespaces` foundation chart does. **Never pass
`--create-namespace`**: Helm 4 replaces the existing namespace with a bare one
and removes the `pod-security.kubernetes.io/enforce: restricted` label.

## Installation

Install in three release revisions, because Helm does not wait between the
objects of one revision:

1. the custom resource definitions alone, which must be established
   before the cluster serving runtimes and the cluster storage container of the
   payload can be created;
2. the control plane without the bundled `ClusterServingRuntime` objects. Their
   validating webhook, `clusterservingruntime.serving.kserve.io`, has
   `failurePolicy: Fail` and is served by `kserve-controller-manager`, so the
   API server rejects every one of them with `connection refused` until that
   Deployment is ready;
3. everything.

```bash
helm install kserve ./applications/kserve/kserve/helm \
  --namespace kserve \
  --values ./applications/kserve/kserve/helm/ci/values-platform.yaml \
  --set payload.resources.enabled=false \
  --wait

for custom_resource_definition_name in $(helm get manifest kserve --namespace kserve |
    awk '$0 == "kind: CustomResourceDefinition" {definition = 1; next}
         definition && /^  name: / {print $2; definition = 0}'); do
  kubectl wait --for=condition=Established \
    "crd/${custom_resource_definition_name}" --timeout=120s
done

helm upgrade kserve ./applications/kserve/kserve/helm \
  --namespace kserve \
  --values ./applications/kserve/kserve/helm/ci/values-platform.yaml \
  --set payload.clusterServingRuntimes.enabled=false \
  --wait --timeout 10m

kubectl wait --for=condition=Available --namespace kserve --timeout=300s \
  deployment/kserve-controller-manager

helm upgrade kserve ./applications/kserve/kserve/helm \
  --namespace kserve \
  --values ./applications/kserve/kserve/helm/ci/values-platform.yaml \
  --wait --timeout 10m
```

Every command passes the complete values file again and no `--reuse-values`,
so no revision depends on the values of an earlier one: both phase keys are
`true` in that file. No command passes `--force-conflicts`; [Upgrade](#upgrade)
gives the reason.

`tests/kserve_helm_install.sh` is this procedure as continuous integration
runs it, followed by the readiness waits of the Kustomize installer.

The Models Web Application is a separate component, `applications/kserve/kserve-ui`.

## Configuration

| Value | Default | Purpose |
| --- | --- | --- |
| `payload.scenario` | `platform` | Rendered Kustomize parity scenario. Only `platform` is supported. |
| `payload.customResourceDefinitions.enabled` | `true` | Render the KServe custom resource definitions. |
| `payload.resources.enabled` | `true` | Render the control plane. Set to `false` for the first release revision. |
| `payload.clusterServingRuntimes.enabled` | `true` | Render the bundled `ClusterServingRuntime` objects of the control plane. Set to `false` for the second release revision. No effect while `payload.resources.enabled` is `false`. |

These four keys are the whole interface. The chart fails when `scenario`,
`customResourceDefinitions` or `resources` is set at the top level, and names
the `payload.` key to use instead, because Helm would otherwise ignore the
value silently.

Values that the Kustomize component declares through patches, such as the
ingress configuration and the controller images, are not exposed. Exposing one
means rendering the resource that carries it from a hand-written template,
which is a separate change.

## Lifecycle

### Custom resource definitions

The definitions are rendered from `templates/` and carry
`helm.sh/resource-policy: keep`. This deviates from Helm's documented
recommendation to place custom resource definitions in `crds/`, deliberately:
Helm never upgrades or deletes anything in `crds/`, which would freeze every
schema at its first installed version. Rendering them as templates keeps the
schemas upgradeable.

Because they are templates rather than `crds/` content, Helm's `--skip-crds`
option has no effect on them. Use `payload.customResourceDefinitions.enabled=false`
when an administrator or another release already owns them.

### Upgrade

```bash
helm upgrade kserve ./applications/kserve/kserve/helm \
  --namespace kserve \
  --values ./applications/kserve/kserve/helm/ci/values-platform.yaml \
  --wait --timeout 10m
```

Pass the same values file as for the installation and do not pass
`--reuse-values`. The definitions are updated to the synchronized upstream
version and every custom resource is kept.

No installation, upgrade or rollback of this chart passes `--force-conflicts`.
Helm 4 applies server-side, and the chart states no field that another
controller owns. The payload omits `rules` of the aggregated
`kubeflow-kserve-admin` cluster role, because the Kubernetes role aggregation
controller owns that field
([aggregated ClusterRoles](https://kubernetes.io/docs/reference/access-authn-authz/rbac/#aggregated-clusterroles)).
It sets no `caBundle` either, which the cert-manager CA injector writes into
the webhook configurations.

`--force-conflicts` is not limited to one field: it covers every object of the
release and overwrites, without a message, each field of the payload that an
administrator or another controller changed in the cluster. A conflict is
therefore a finding to inspect, not a reason to add the option. An upgrade that
stopped on a conflict may already have applied other objects of the release, so
do not assume that nothing changed. `helm upgrade --dry-run=server` is not
conflict evidence: it does not apply, so it exits 0 where the real upgrade
stops on a conflict.

### Rollback

```bash
helm history kserve --namespace kserve
helm rollback kserve <revision> --namespace kserve --wait --timeout 10m
```

Roll back only to a revision that installed everything. Revision 1 of the
installation above holds the definitions alone; rolling back to it deletes the
whole control plane, so it is not a rollback target. Neither is revision 2,
which lacks the cluster serving runtimes. Revision 3 is the first full one.

A release installed from an earlier revision of this chart keeps that
revision's manifest in its history, and regenerating the chart does not rewrite
it: the stored manifest still states `rules: []` for `kubeflow-kserve-admin`.
`helm upgrade` from such a release to this chart needs no option. Rolling back
to the stored revision reintroduces `rules: []`, so such a revision is not a
rollback target either. Observed on a cluster: `helm rollback` to it stops with
`conflict with "clusterrole-aggregation-controller": .rules`, changes no object
in the cluster, and leaves the release without a `deployed` revision, because
Helm records the rollback as `failed` after it has marked the previous revision
`superseded`. The `helm upgrade` command above, with this chart and without any
option, then creates a `deployed` revision again.

### Serving during an upgrade or a rollback

The supported claim is recovery: after the upgrade or the rollback has
completed and the controllers are ready again, existing `InferenceService`
objects reconcile and serve. Uninterrupted serving during the operation is not
claimed and not measured. The KServe section of `tests/helm_lifecycle_test.sh`
verifies, after the reinstallation, that a retained `InferenceService` becomes
Ready again and that a fresh `InferenceService` is reconciled to Ready.

### Uninstall and reinstall

The retention policy protects the definitions, and with them the
objects that users created from them, such as every `InferenceService`,
`ServingRuntime` and `TrainedModel`. It protects nothing else. Everything else
the release owns is deleted, including the `ClusterServingRuntime` and
`ClusterStorageContainer` objects that the chart itself provides, the
controllers, the webhooks and the inference service configuration.

| operation | definitions | objects created by users | objects provided by the chart |
| --- | --- | --- | --- |
| `helm install` | created | none yet | created |
| `helm upgrade` | updated | kept | updated |
| `helm rollback` to a full revision | restored to that revision | kept | restored to that revision |
| `helm uninstall` | kept (`helm.sh/resource-policy: keep`) | kept | deleted, including every bundled `ClusterServingRuntime` and `ClusterStorageContainer` |
| `helm install` again | adopted by the release | kept | created again |

An uninstalled release serves nothing reliably: no controller reconciles the
kept objects, and an `InferenceService` that refers to a bundled
`ClusterServingRuntime` has lost that runtime. No inference is promised
between `helm uninstall` and the next installation.

Installing again with the release name `kserve` in the namespace `kserve`
adopts the kept definitions, because they still carry the ownership metadata
of that release; any other release name or namespace is refused by Helm. Use
the three-revision installation above; afterwards the controllers reconcile the
kept objects again.

## How this chart is kept up to date

`COMMIT` in `scripts/synchronize-kserve-kserve-manifests.sh` is the single
upstream version. The script copies the upstream bundle, regenerates the
payloads from the component, sets `appVersion` in the `kserve` and the
`kserve-payload` chart and verifies that the dependency version the parent
declares equals the version of `kserve-payload`:

```bash
python3 -m pip install pyyaml "ruamel.yaml==0.19.1"
KUBEFLOW_SYNCHRONIZE_NO_COMMIT=true \
  ./scripts/synchronize-kserve-kserve-manifests.sh
```

Do not edit files under `charts/kserve-payload/manifests/` directly. Review a generated payload change
by resource identity and upstream source boundary first, then regenerate and
confirm `git diff` is empty. The replay proves the generator is deterministic; it
cannot tell you whether a new upstream release introduced an unintended webhook,
permission or policy change.

## Kustomize Mapping

- `ci/values-platform.yaml`: `applications/kserve/kserve`, except
  `Namespace/kserve`, which the `kubeflow-namespaces` chart renders and
  compares.

## Comparison

```bash
helm lint applications/kserve/kserve/helm --namespace kserve
python3 tests/run_helm_kustomize_comparison.py kserve platform
python3 tests/helm_release_size.py kserve
python3 tests/kserve_helm_chart_test.py
python3 tests/kserve_helm_manifest_generator_test.py
python3 tests/kserve_helm_release_size_test.py
python3 scripts/generate-kserve-helm-manifests.py --check
```

The KServe section of `tests/helm_lifecycle_test.sh`, run by the
`helm_lifecycle_test` job of the Helm integration workflow, exercises a changed
upgrade observed on the live controller, the
rollback, the uninstallation that keeps the definitions and the user
`InferenceService`, and the reinstallation through `tests/kserve_helm_install.sh`.
Installation from a packaged chart is not exercised by a workflow.

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../../tests/README.md).
