# Spark Operator Helm Chart

This chart installs the Kubeflow Spark Operator with the Kubeflow platform
defaults.

Unlike the other component charts in this repository, it vendors nothing. The
Kustomize baseline at `applications/spark/spark-operator/base/resources.yaml` is
itself produced by running `helm template` against the upstream Spark Operator
chart, so this chart depends on that same published chart and adds only the
resources Kubeflow owns. Reproducing the baseline as a payload would mean going
from Helm to text to Kustomize back to text back to Helm, and would replace a
maintained chart with a copy of its output.

It installs:

- upstream Spark Operator `v2.5.2`, as a chart dependency
- three Kubeflow aggregated `ClusterRoles` granting Spark application access to
  the `kubeflow-admin`, `kubeflow-edit` and `kubeflow-view` roles

Everything else Kubeflow changes is expressed through upstream values. There are
no patches.

## Prerequisites

| Chart | Provides |
| --- | --- |
| `kubeflow-namespaces` | `Namespace/kubeflow` and `NetworkPolicy/spark-operator-webhook` |
| `kubeflow-platform` | shared Kubeflow platform RBAC |

`NetworkPolicy/spark-operator-webhook` lives in
`common/kubeflow-namespace/base/kubeflow/`, not with this component. It belongs to
the foundation chart and this chart deliberately does not create it: a resource
belongs to exactly one Helm release.

## Installation

The release name and the namespace are both fixed.

```bash
helm repo add spark-operator https://kubeflow.github.io/spark-operator
helm dependency build ./applications/spark/spark-operator/helm
helm install spark-operator ./applications/spark/spark-operator/helm \
  --namespace kubeflow \
  --wait
```

**The release must be named `spark-operator`.** The upstream chart derives every
resource name and, more importantly, `spec.selector.matchLabels` from
`.Release.Name`. A different release name produces different selector labels,
which Kubernetes treats as immutable on an existing Deployment.

**The release namespace must be `kubeflow`**, and the chart refuses to render
anywhere else. It does not create that namespace; `kubeflow-namespaces` does.

**Do not pass `--create-namespace`.** Helm creates a bare namespace carrying only
a `name` label, and because Helm 4 applies server-side by default this removes
`pod-security.kubernetes.io/enforce` from `kubeflow` — disabling restricted Pod
Security for the namespace the whole platform runs in. Repair it with:

```bash
kubectl label namespace kubeflow \
  pod-security.kubernetes.io/enforce=restricted --overwrite
```

## Configuration

| Value | Default | Purpose |
| --- | --- | --- |
| `spark-operator.enabled` | `true` | Install the upstream chart. Disable to render only the Kubeflow roles. |
| `spark-operator.spark.jobNamespaces` | `[""]` | Namespaces watched for Spark applications. |
| `spark-operator.controller.labels` | `sidecar.istio.io/inject: "false"` | Controller pod labels. |
| `spark-operator.webhook.enable` | `true` | Run the admission webhook. |
| `spark-operator.webhook.port` | `9443` | Admission webhook port. |
| `spark-operator.webhook.labels` | `sidecar.istio.io/inject: "false"` | Webhook pod labels. |
| `kubeflow.aggregatedRoles.enabled` | `true` | Create the three Kubeflow aggregated `ClusterRoles`. |

Every other upstream value is available under the `spark-operator` key.

### `jobNamespaces` is a list containing the empty string

The default is `[""]`, not `[]`. They are different configurations:

- `[""]` renders `--namespaces=""`, meaning every namespace. This is what the
  Kustomize baseline produces, and why the operator is granted cluster-wide
  permissions.
- `[]` renders no `--namespaces` argument at all.

**Naming namespaces here has an ownership consequence.** The upstream chart
creates a `ServiceAccount`, `Role` and `RoleBinding` inside every listed
namespace. In Kubeflow those are Profile namespaces, whose RBAC the Profile
controller owns, and `helm uninstall` would delete resources from them. The
Kubeflow example at `applications/spark/sparkapplication_example.yaml` runs as
`serviceAccount: default-editor`, which Profiles already provide, so this list is
left alone.

## Custom resource definition lifecycle

**The three Spark custom resource definitions are not upgraded by `helm upgrade`
and not deleted by `helm uninstall`.**

They come from the upstream chart's `crds/` directory. Helm states plainly that
there is *"no support at this time for upgrading or deleting CRDs"*
([CRD best practices](https://helm.sh/docs/chart_best_practices/custom_resource_definitions/)),
and a chart cannot override a dependency's `crds/` directory.

This is the one place where wrapping costs something. The
`applications/dashboard/helm` chart renders its own definitions from `templates/`
with `helm.sh/resource-policy: keep`, so `helm upgrade` updates them. That option
is not available here, because these definitions belong to the dependency.

Upstream ships `hook.upgradeCrd`, a `pre-install,pre-upgrade` Job that re-applies
them. **It cannot be enabled on Kubeflow.** The Job sets no `runAsNonRoot` and no
`seccompProfile`, exposes no security context value, and its image runs as root,
so it fails restricted Pod Security admission in `kubeflow`.

| Operation | Behaviour |
| --- | --- |
| `helm install` | Applies the bundled definitions server-side as field manager `helm`, also when they already exist. |
| `helm upgrade` | **Does not** update them. |
| `helm uninstall` | Leaves them and every Spark application in place. |

### Definition maintenance

An administrator applies a definition change from a new release before the chart
upgrade, as the field manager `kubeflow-crd-maintenance`. Keep exactly this name
for every later update.

1. Extract only the definitions, from the upstream chart version that the target
   release of this chart pins:

   ```bash
   helm show crds spark-operator \
     --repo https://kubeflow.github.io/spark-operator --version 2.5.2 \
     > target-crds.yaml
   ```

   Check that the file holds only the three intended definitions. Schema
   compatibility, storage version compatibility and any data migration are
   separate prerequisites; `--force-conflicts` performs none of them.

2. Preview on the server without force:

   ```bash
   kubectl apply --server-side --field-manager=kubeflow-crd-maintenance \
     --dry-run=server -f target-crds.yaml
   ```

   When it passes, repeat it without `--dry-run=server` and continue with step 4.
   No force is needed.

3. Helm created the definitions server-side, so a changed definition is refused
   with `conflict with "helm": .spec.versions`. The message does not name the
   definition; it is the one that is not reported as `serverside-applied`.
   Inspect the conflicting fields and their managers:

   ```bash
   kubectl get crd sparkapplications.sparkoperator.k8s.io -o yaml --show-managed-fields
   ```

   Stop when a manager other than `helm` or `kubeflow-crd-maintenance` owns a
   conflicting field. Only after this review, preview and then apply the
   handover with the same manager and the same file:

   ```bash
   kubectl apply --server-side --field-manager=kubeflow-crd-maintenance \
     --force-conflicts --dry-run=server -f target-crds.yaml
   kubectl apply --server-side --field-manager=kubeflow-crd-maintenance \
     --force-conflicts -f target-crds.yaml
   ```

4. Check that the definitions are established, and with `kubectl explain` that a
   field which the new version changes carries the intended schema. Then upgrade
   the chart.

   ```bash
   kubectl wait --for=condition=Established --timeout=60s -f target-crds.yaml
   ```

**One forced apply does not end every later conflict.** It hands over only the
fields that changed: `kubeflow-crd-maintenance` then owns `.spec.versions` of the
changed definition alone, and a further change to it passes without force.
`helm` still shares every unchanged field, including `.spec.versions` of an
unchanged definition, so the first change there conflicts with `helm` again. A
different field manager conflicts with `kubeflow-crd-maintenance` as well.

**Reinstall with `--skip-crds` once the definitions are administrator-managed**,
with compatible definitions present first. Pass it to `helm install`, and to
`helm upgrade --install` because its install side behaves the same. Without it,
Helm applies the bundled definitions again as `helm`, without force. When they
differ from the maintained ones, the installation fails before it creates a
release, with `conflict with "kubeflow-crd-maintenance": .spec.versions`. When
they are equal, it succeeds, and `helm` shares `.spec.versions` again, so the
next change needs force again.

**Never delete and recreate a definition to resolve ownership.** Deleting a
definition deletes every object of its kind, for `sparkapplications` every Spark
application.

Verified on a cluster, in this scope: one single-node kind cluster, Kubernetes
1.36.1, Helm 4.2.2, the pinned definitions with one changed `description` in
`sparkapplications`. Steps 1 to 4, an unchanged `helm upgrade` without any force
option, and both reinstallation outcomes were observed. The equal case used a
local copy of the dependency with the same change, and the statements about later
changes come from server dry runs. The three definitions and a completed Spark
application kept their UIDs, the changed schema stayed in place, and a new
application completed after the reinstallation with `--skip-crds`. An upgrade to
a newer upstream version was not tested. The earlier check against the
definitions of upstream chart 2.2.1 was a server dry-run conflict probe, not a
supported downgrade and not an upgrade to a newer version.

## Uninstallation and reinstallation

`helm uninstall` deletes every object of the release. It leaves the three
definitions, every Spark application, and three objects that the operator creates
at run time and that are therefore not part of the release:
`Secret/spark-operator-webhook-certs`, `Lease/spark-operator-controller-lock` and
`Lease/spark-operator-webhook-lock`. There is no claim that a running application
continues without the operator.

A reinstallation applies the bundled definitions again as field manager `helm`.
For a definition that `helm` still owns with identical content, this changed
nothing on a live cluster: the UID and the `resourceVersion` stayed the same.
For administrator-managed definitions, reinstall with `--skip-crds` as described
in [Definition maintenance](#definition-maintenance).

After a reinstallation the new webhook pod is ready before it is the leader: it
first waits for the `Lease` of the previous pod to expire, and it writes
`caBundle` into the two webhook configurations only as the leader. That took 16
to 19 seconds on a live cluster, and until then the API server rejected a Spark
application with `x509: certificate signed by unknown authority`.
`tests/spark_helm_install.sh` therefore waits for `caBundle`.
`tests/spark_helm_lifecycle_test.sh` verified the rest on the same cluster: the
reinstalled controller completes a new application, leaves a completed one
alone, and submits it again when its specification changes.

## How this chart is kept up to date

`scripts/synchronize-spark-operator-manifests.sh` owns a single version, `COMMIT`,
and drives everything from it: the rendered Kustomize baseline, the chart
`appVersion`, the pinned dependency version and this file. The dependency is
pinned exactly rather than to a range, because the comparison below only proves
something if both sides render the same upstream chart version.

The baseline is Helm output, so the script requires exactly the Helm version that
`.github/workflows/helm-kustomize-comparison.yml` pins and stops before changing
any file when another version is installed.

Before committing, that script runs `helm lint`. Parity runs in continuous
integration: the Helm and Kustomize comparison workflow compares the chart with
the baseline on the pull request that the synchronization opens, so a release
that changes something the chart configures fails there rather than landing
silently.

## Kustomize Mapping

- `ci/values-kubeflow.yaml`: `applications/spark/spark-operator/overlays/kubeflow`

## Comparison

```bash
helm lint applications/spark/spark-operator/helm --namespace kubeflow
python3 tests/run_helm_kustomize_comparison.py spark-operator --all-scenarios
python3 tests/spark_operator_helm_chart_test.py
```

The chart tests need the upstream chart from its repository. When it cannot be
downloaded, the tests that render the chart are skipped, the last lines of the
output count them, and the command exits with status 2: that run is incomplete,
not passed. In GitHub Actions the same condition is an error.

Both sides of that comparison render the same upstream chart, so agreement is
close to tautological. What it proves is narrow but worth having: that the values
in this chart reproduce the flags the synchronization script passes, and that the
three Kubeflow roles survive. It says nothing about whether the upstream chart is
itself correct.
