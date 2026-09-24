# Kubeflow Workspaces Helm Chart

> **DANGER: Workspaces (Notebooks v2) is still pre-GA.**
>
> **DO NOT DEPLOY THIS TO A PRODUCTION CLUSTER.**
>
> See this for the current status:
> <https://www.kubeflow.org/docs/components/notebooks/notebooks-v2-pre-ga-banner>

This chart renders the Kubeflow Workspaces Kustomize resources
(`applications/workspaces/overlays/istio`: controller, backend and frontend)
with Helm. Kustomize remains the source of truth. `kubeflow/notebooks` publishes
no Helm chart for Workspaces, so this is a generated payload chart, not a
wrapper: the synchronization script builds the overlay once and writes
deterministic payloads under `manifests/`, which two small templates load with
`.Files.Get`.

Helm does not send `.Files.Get` content through the template renderer, so Go
template delimiters that upstream manifests legitimately contain are emitted
literally. The WorkspaceKind definition already documents expressions such as
`{{ httpPathPrefix 'jupyterlab' }}`; evaluating them as chart code would fail
the render.

## Prerequisites

Install these first, in this order:

1. The platform foundation charts, which create the `kubeflow` namespace
   (`common/kubeflow-namespace/helm`) and the Kubeflow roles.
2. cert-manager, ready to issue certificates. The chart renders an `Issuer` and
   a `Certificate` for the validating webhook, and cert-manager injects the
   certificate authority bundle into both webhooks of the
   `ValidatingWebhookConfiguration`. Both definitions carry the
   `cert-manager.io/inject-ca-from` annotation as well, but they declare no
   conversion webhook in this version, so there is no field to inject into: on a
   cluster their `spec.conversion` is `strategy: None` and cert-manager owns no
   field of them.
3. Istio. The chart renders `VirtualService`, `DestinationRule` and
   `AuthorizationPolicy` objects, and the namespace it creates is labelled
   `istio-injection: enabled`.

The Workspaces menu entry of the Central Dashboard
(`applications/workspaces/components/centraldashboard`) is not part of this
chart.

## Install

```bash
helm install kubeflow-workspaces applications/workspaces/helm \
  --namespace kubeflow \
  --values applications/workspaces/helm/ci/values-istio.yaml \
  --wait --timeout 5m
```

This is one revision. The payload contains no custom resource of the chart's own
kinds, so there is no two-phase installation.

The release is listed in `kubeflow`, not in `kubeflow-workspaces`:

```bash
helm list -n kubeflow
```

## Upgrade And Rollback

```bash
helm upgrade kubeflow-workspaces applications/workspaces/helm \
  --namespace kubeflow \
  --values applications/workspaces/helm/ci/values-istio.yaml \
  --wait --timeout 5m
helm history kubeflow-workspaces --namespace kubeflow
helm rollback kubeflow-workspaces <revision> --namespace kubeflow --wait --timeout 5m
```

`helm upgrade` and `helm rollback` need no force option.
`kubeflow-workspaces-admin`, `kubeflow-workspaces-edit` and
`kubeflow-workspaces-view` are
[aggregated ClusterRoles](https://kubernetes.io/docs/reference/access-authn-authz/rbac/#aggregated-clusterroles):
the Kubernetes aggregation controller owns their `rules` field and fills it from
the ClusterRoles that each `aggregationRule` selects. The Kustomize baseline
declares `rules: []` on all three. The chart omits the field, because a manifest
that sets it, even to an empty list, claims a field that the controller owns. The
`aggregationRule` selectors, the labels and the ClusterRoles that contribute the
permissions are the ones of the Kustomize baseline.

A release that was installed from an earlier revision of this chart still
stores `rules: []` for the three aggregated ClusterRoles in its release history.
`helm upgrade` from such a release to this chart needs no force option.
`helm rollback` to such a stored revision applies `rules: []` again and fails
with a conflict against `clusterrole-aggregation-controller` on `.rules` of all
three roles. As observed, the failed rollback changes neither the roles and
their rules nor the Deployments and their pods, but it leaves no revision
`deployed`: `helm status` reports `failed`. `helm upgrade` with this chart,
again without a force option, recovers. Roll back only to revisions created from
this chart revision or a later one. `helm upgrade --dry-run=server` is not
conflict evidence, because it does not apply: with the earlier chart revision it
exits with 0, while the real upgrade fails with the conflict.

Every `helm upgrade` and `helm rollback`, including a failed one, rewrites
`NetworkPolicy/workspaces-controller` with identical content: only its
`generation` and the timestamp of the `helm` field manager change. The payload
declares `from: []` for it, as the Kustomize baseline does, and the stored object
does not contain that field. An unchanged upgrade wrote no other object.

## Release Namespace And Workload Namespace

Other Kubeflow charts install into the namespace that holds their workloads.
This chart deliberately deviates from that rule:

- The **release record** is stored in `kubeflow`. `templates/validate-namespace.yaml`
  refuses every other release namespace, including `kubeflow-workspaces`.
- The chart **owns** `Namespace/kubeflow-workspaces`, with the labels of the
  Kustomize baseline (`istio-injection: enabled`,
  `pod-security.kubernetes.io/enforce: restricted`,
  `app.kubernetes.io/part-of: kubeflow-workspaces`). Every namespaced object in
  the payload declares `namespace: kubeflow-workspaces` explicitly, so nothing
  falls back to the release namespace.

The reason is that a release stored inside `kubeflow-workspaces` would keep its
record in a namespace that the same release creates and deletes. Storing it in
`kubeflow`, which exists before this chart, keeps the record outside that
namespace. The `kubeflow-namespaces` foundation chart sets the precedent: its
release is stored in one namespace while it renders others. Do not use
`--create-namespace`; it is neither an ownership nor an adoption mechanism.

## Namespace Contract

| Situation | Behavior |
| --- | --- |
| Fresh platform installation | The only supported path. |
| `kubeflow-workspaces` already exists and is not owned by this release, for example from a Kustomize installation | Helm's ownership check refuses the installation with the error below and leaves no release record behind. The chart offers no `--take-ownership` recipe and no silent adoption. Migrating a Kustomize installation is out of scope. |
| `helm uninstall` | The `kubeflow-workspaces` namespace is **deleted, together with everything inside it, including objects that this release does not own**. Do not keep anything of your own in this namespace. |
| What remains after `helm uninstall` | The two definitions (`helm.sh/resource-policy: keep`), every `Workspace` with its PersistentVolumeClaim in the profile namespaces, and every cluster-scoped `WorkspaceKind`. |
| Reinstallation | Only after the namespace has finished terminating. The same release name and release namespace adopt the kept definitions again. |

The refusal of a namespace that the release does not own, as Helm 4.2.2 prints
it for a namespace created with `kubectl create namespace kubeflow-workspaces`:

```text
Error: INSTALLATION FAILED: unable to continue with install: Namespace "kubeflow-workspaces" in namespace "" exists and cannot be imported into the current release: invalid ownership metadata; label validation error: missing key "app.kubernetes.io/managed-by": must be set to "Helm"; annotation validation error: missing key "meta.helm.sh/release-name": must be set to "kubeflow-workspaces"; annotation validation error: missing key "meta.helm.sh/release-namespace": must be set to "kubeflow"
```

The namespace is deleted on purpose. `kubeflow-workspaces` is a dedicated system
namespace for the controller, the backend and the frontend. User data lives
elsewhere: `Workspace` objects and their PersistentVolumeClaims are in the
profile namespaces, and `WorkspaceKind` is cluster-scoped. Deleting the
namespace matches what removing the Kustomize component does, and a kept
namespace would stay behind with its Istio injection and Pod Security labels
and no owner.

Retained objects do **not** mean that the Workspaces API stays usable. After
`helm uninstall` the controller and the validating webhook are gone: nothing
reconciles a `Workspace`, and admission is no longer validated because the
webhook configuration was deleted with the release. Treat the time between
uninstall and reinstall as an outage of Workspaces, not as a degraded mode.
A `WorkspaceKind` that is in use carries the
`notebooks.kubeflow.org/workspacekind-protection` finalizer, which only the
controller removes. Deleting one during that time is not validated and leaves it
terminating with that finalizer; once the chart is installed again, the
controller removes it as soon as no `Workspace` uses it any more.

The uninstall does not touch the pod of a running `Workspace`: on the test
cluster the pod kept its UID through uninstall and reinstall. After the
reinstallation the webhook rejects an invalid `Workspace` again
(`spec.kind: Invalid value: ...: workspace kind "..." not found`), and the
controller reconciles the retained `Workspace` again: pausing it removes the pod
and resuming it starts a new one.

## Deleting A Workspace

`kubectl delete workspace` removes what the controller created for it, because
each of these objects carries an owner reference to the `Workspace`: the
StatefulSet with its pod, the Service, the VirtualService, the ServiceAccount
and the RoleBindings. The PersistentVolumeClaim that `spec.podTemplate.volumes`
names is not owned by the `Workspace`. It remains with the same UID and is
deleted separately when its data is no longer needed.

Wait for the namespace to terminate before installing again:

```bash
helm uninstall kubeflow-workspaces --namespace kubeflow --wait
kubectl wait --for=delete namespace/kubeflow-workspaces --timeout=300s
```

## Configuration

| Value | Default | Purpose |
| --- | --- | --- |
| `scenario` | `istio` | Rendered Kustomize parity scenario. Only `istio` is supported. |
| `customResourceDefinitions.enabled` | `true` | Render the Workspace and WorkspaceKind custom resource definitions. |

There is deliberately no switch for an externally managed namespace; that is
not a supported scenario. Values that the Kustomize baseline declares, such as
container images, are **not** exposed. Adding them means rendering the
resources that carry them from hand-written templates, which is a separate
change.

## Definitions And Webhooks

`workspacekinds.kubeflow.org` (cluster-scoped) and `workspaces.kubeflow.org`
(namespaced) are rendered from `templates/` and carry
`helm.sh/resource-policy: keep`. This deviates from Helm's documented
recommendation to place custom resource definitions in `crds/`, deliberately:
Helm never upgrades or deletes anything in `crds/`, which would freeze both
schemas at their first installed version while upstream publishes a new beta
about every two weeks. Rendering them as templates makes both schemas part of
what `helm upgrade` applies, while the retention policy stops `helm uninstall`
from deleting existing Workspaces and WorkspaceKinds.

Because they are templates rather than `crds/` content, Helm's `--skip-crds`
option has no effect on them. Use `customResourceDefinitions.enabled=false` when
an administrator or another release already owns them.

In this version (`v2.0.0-beta.2`) neither definition declares a conversion
webhook: each serves the single version `v1beta1`, and the upstream conversion
patch is commented out. Both definitions do carry the
`cert-manager.io/inject-ca-from` annotation. `tests/workspaces_helm_chart_test.py`
fails when a later synchronization introduces a conversion webhook, because the
uninstall contract above would then need to be revisited: retained definitions
would point at a webhook service that no longer exists.

The chart does render a `ValidatingWebhookConfiguration` with failure policy
`Fail` for `Workspace` (create, update) and `WorkspaceKind` (create, update,
delete). It is served by the controller through `workspaces-webhook-service`
with a certificate that cert-manager issues into `kubeflow-workspaces`.

## Kustomize Mapping

- `ci/values-istio.yaml`: `applications/workspaces/overlays/istio`

`kustomize/kustomization.yaml` is the generator input: that overlay plus one
patch that adds `helm.sh/resource-policy: keep` to every definition. The
payloads keep what Kustomize renders, including the content-hashed ConfigMap
name, with two controlled transforms: the keep annotation on both definitions,
and the omitted `rules` field of the three aggregated ClusterRoles
([Upgrade And Rollback](#upgrade-and-rollback)).

## Comparison

```bash
helm lint applications/workspaces/helm --namespace kubeflow
python3 tests/run_helm_kustomize_comparison.py kubeflow-workspaces istio
python3 tests/run_helm_kustomize_comparison.py kubeflow-workspaces --all-scenarios
python3 tests/workspaces_helm_chart_test.py
```

How this chart is compared, including the retained definitions, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../tests/README.md). The `Namespace` object is part of
the comparison.

`tests/workspaces_helm_install.sh` installs the chart on a cluster.
Run the manual lifecycle and upgrade scripts only on a disposable test cluster.
The lifecycle fixture overwrites the cluster-wide `jupyterlab` WorkspaceKind.
`tests/workspaces_helm_lifecycle_test.sh` exercises explicit `Workspace`
deletion, uninstall with a retained `Workspace`, reinstallation and the refusal
of a namespace that the release does not own; it is destructive and is not part
of a workflow. `tests/workspaces_helm_upgrade_test.sh` runs an unchanged
upgrade, an upgrade to a changed copy of the chart and a rollback, all without a
force option. After each it checks that the three aggregated ClusterRoles carry
rules, that Helm is not a manager of that field, and that a ServiceAccount bound
to `kubeflow-workspaces-edit` may still create a `Workspace` and may still not
read a `Secret`; it is not part of a workflow either. It creates a uniquely
named namespace for that ServiceAccount and deletes only a namespace that it has
created, which `tests/workspaces_helm_upgrade_cleanup_test.sh` verifies without
a cluster, with stub `kubectl` and `helm` executables.

## Keeping The Chart Up To Date

Regenerate the payloads from the local Kustomize inputs, or verify them
without writing:

```bash
python3 -m pip install pyyaml "ruamel.yaml==0.19.1"
python3 scripts/generate-workspaces-helm-manifests.py
python3 scripts/generate-workspaces-helm-manifests.py --check
```

Import a new upstream release through the component synchronization script. It
updates `appVersion` in `Chart.yaml`, regenerates the payloads and lints the
chart:

```bash
KUBEFLOW_SYNCHRONIZE_NO_COMMIT=true \
  ./scripts/synchronize-kubeflow-workspaces-manifests.sh
```

Do not edit files under `manifests/` directly. Review a generated payload change
by resource identity and upstream source boundary first, then regenerate and
confirm `git diff` is empty. The replay proves the generator is deterministic; it
cannot tell you whether a new upstream release introduced an unintended webhook,
permission or policy change.
