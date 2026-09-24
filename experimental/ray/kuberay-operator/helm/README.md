# Kubeflow KubeRay operator Helm chart

This wrapper installs the same upstream KubeRay operator chart that produces
`experimental/ray/kuberay-operator/base/resources.yaml`. The dependency and
`Chart.lock` pin version 1.6.2. Upstream values express the distribution's
init-container and restricted-PSS changes; the only added objects are the three
Kubeflow RBAC roles. The `kubeflow` comparison scenario covers all 20 objects,
including four definitions, against the distribution overlay without allowances.

The chart remains beside its existing experimental component. This does not
promote Ray to a stable supported Kubeflow component or relocate its sources.

## Prerequisites and installation

Use Helm 4. The foundation charts own the existing `kubeflow` namespace and
Kubeflow shared roles. Ray workloads use existing Profile namespaces, their
`default-editor` service accounts and Istio. The operator chart creates no
namespace or user workload. One cluster-wide operator release serves all Profiles.

From the repository root:

```bash
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm dependency build experimental/ray/kuberay-operator/helm
helm install kuberay-operator experimental/ray/kuberay-operator/helm \
  --namespace kubeflow --wait --timeout 180s
```

The chart rejects any other release name or namespace. The fixed release name
preserves upstream Deployment selectors and RBAC references. Do not use
`--create-namespace`: the foundation must retain its namespace labels and policy.
`tests/ray_helm_install.sh` performs this installation through a disposable chart
copy, waits for all four definitions and waits for the operator Deployment.

Do not run this installation over a Kustomize-owned operator. Moving an existing
installation requires an explicit resource-ownership migration and verified
immutable selectors; this draft does not claim an in-place adoption procedure.

## Configuration

| Upstream value below `kuberay-operator` | Platform default | Purpose |
| --- | --- | --- |
| `env` | `ENABLE_INIT_CONTAINER_INJECTION=false` | Matches the distribution's Istio overlay |
| `podSecurityContext.seccompProfile.type` | `RuntimeDefault` | Restricted-PSS Pod default |
| `securityContext.seccompProfile.type` | `RuntimeDefault` | Restricted-PSS container default |
| `image.repository`, `image.tag` | Pinned upstream operator image | Private mirrors and deliberate operator changes |
| `replicas` | `1` | Operator replicas with upstream leader election |

Other upstream settings remain available through the dependency; only the
platform defaults have a Kustomize parity scenario. Upstream lists replace the
entire list when overridden: an `env` override must preserve the platform entry
unless a different init-container policy has been tested. Restricted-PSS fields
inherited from upstream remain enabled. Changes to names, namespace scope,
RBAC, scheduler integration or feature gates are not additional tested platform
scenarios merely because the upstream chart exposes those settings.

`kubeflow-kuberay-admin` intentionally keeps `rules: []`: it has aggregate-to
labels but no `aggregationRule`, so it is not the controller-owned-field exception.
The shared aggregated-role repair in pull request #3609 is still required for
upgrading the foundation charts until that change merges.

## Definitions and lifecycle

The four upstream definitions are `rayclusters.ray.io`, `rayjobs.ray.io`,
`rayservices.ray.io` and `raycronjobs.ray.io`. They stay in the dependency's
`crds/` directory, a deliberate wrapper exception to the generated charts'
`templates/` plus `helm.sh/resource-policy: keep` convention. Keeping upstream
packaging avoids a second schema owner and a forked operator chart.

Helm installs definitions before ordinary resources. They are not part of the
upgrade/rollback-managed manifest, and uninstall leaves them and their custom
resources in place. The controller and Kubeflow-specific roles are removed;
existing Ray resources stop being reconciled until a compatible controller
returns. This is retention, not a guarantee of application availability during
operator removal. Never remove the definitions to fix an installation problem.

**A chart upgrade or rollback does not update or roll back these schemas.** A
version change needs an administrator-reviewed definition update before the
operator upgrade. Check stored versions and existing Ray resources against the
target schema, and back up the definitions and custom resources first. Extract
only the definitions from the exact target dependency:

```bash
helm show crds experimental/ray/kuberay-operator/helm > target-ray-crds.yaml
kubectl apply --server-side --field-manager=kubeflow-crd-maintenance \
  --dry-run=server -f target-ray-crds.yaml
```

When this preview succeeds, repeat without `--dry-run=server`. A changed schema
can conflict with manager `helm`, which created the definitions. Inspect each
conflicting definition with `kubectl get crd NAME -o yaml --show-managed-fields`.
Stop if another owner or a schema compatibility problem is involved. Only after
reviewing a deliberate handover from `helm` to `kubeflow-crd-maintenance`, preview
and apply the same file with that manager and `--force-conflicts`. This is a
specific administrative ownership transfer, not a routine Helm upgrade flag.
An unchanged field can remain shared and cause a later ownership conflict.
Wait for all definitions to be Established and verify the changed schema before
upgrading the operator.

**On reinstall after administrator maintenance, use `--skip-crds`.** Helm 4's
installation path can apply its bundled definitions to existing definitions;
it must not become a second writer of administrator-maintained schemas. With
compatible definitions present first:

```bash
helm install kuberay-operator experimental/ray/kuberay-operator/helm \
  --namespace kubeflow --skip-crds --wait --timeout 180s
# Equivalent scripted installation or upgrade:
RAY_CRDS_MANAGED_EXTERNALLY=true ./tests/ray_helm_install.sh
```

The same option matters for the install side of `helm upgrade --install`.
A rollback is safe only when the installed schemas and existing resources remain
compatible with the older operator. Reinstalling a compatible release restores
reconciliation; it does not recreate resources deleted independently.

## Maintenance and verification

`experimental/ray/Makefile` is the version source. Change its pin deliberately,
then run `scripts/synchronize-ray-manifests.sh`; `make -C experimental/ray
kuberay-operator/base` runs the same synchronization without a commit. The script
renders the upstream dependency into the Kustomize base, refreshes chart metadata
and the lock only when resolved dependencies change, copies the Kubeflow roles,
lints the chart, and stages only its four named generated paths. It uses a
disposable dependency directory and never commits downloaded archives. The
script does not stage manual edits to the Makefile or synchronizer. Its version and repository come from the Makefile; use that source rather
than an environment override for version changes.

```bash
python3 tests/run_helm_kustomize_comparison.py kuberay-operator --all-scenarios
python3 tests/helm_release_size.py kuberay-operator
python3 tests/ray_helm_chart_test.py -v
```

The Helm integration workflow installs this chart, runs the existing Ray fixture
with `RAY_MANAGED_BY_HELM=true`, and then runs `tests/ray_helm_lifecycle.sh`.
The fixture executes distributed tasks and checks their results as well as the
dashboard version. Its Helm mode never applies or deletes the operator bundle;
cleanup selects only its RayCluster's Pods. The legacy Kustomize workflow keeps
its original operator owner.

The fixture leaves an existing `istio-injection=enabled` Profile namespace label
unchanged and refuses a conflicting value. If the label is absent, it enables
injection temporarily and removes only that added label during cleanup, with
atomic checks of the namespace UID and label value. It refuses to run if its
RayCluster, AuthorizationPolicy or headless Service already exists, and a failed
identity read stops the test.

The lifecycle script is destructive to its operator release and requires
`RUN_HELM_LIFECYCLE_TESTS=true` on a disposable cluster. It holds a RayJob with
`suspend: true` and the upstream-required `shutdownAfterJobFinishes: true`,
waits for `Suspended`, and compares definition schemas, object
UIDs, the Job specification and namespace UIDs across same-version definition
maintenance, unchanged upgrade, replica change, rollback, uninstall and
reinstall. It then runs real distributed work after recovery. It leaves the
operator installed. On failure, inspect the retained fixture and release state;
there is no automatic forced cleanup or claimed recovery.

This draft has local rendering, size and command-boundary tests. Its cluster
workflow and lifecycle script must pass before it is described as lifecycle
validated; neither a template render nor a passing storage-size test proves that.
