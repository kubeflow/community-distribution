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

**The three Spark custom resource definitions are installed once and are not
upgraded by `helm upgrade`.**

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
| `helm install` | Creates the definitions if absent. |
| `helm upgrade` | **Does not** update them. |
| `helm uninstall` | Leaves them and every Spark application in place. |

Apply a definition change from a new release manually:

```bash
kubectl apply --server-side --force-conflicts \
  -f https://github.com/kubeflow/spark-operator/tree/v2.5.2/charts/spark-operator-chart/crds
```

## How this chart is kept up to date

`scripts/synchronize-spark-operator-manifests.sh` owns a single version, `COMMIT`,
and drives everything from it: the rendered Kustomize baseline, the chart
`appVersion`, the pinned dependency version and this file. The dependency is
pinned exactly rather than to a range, because the comparison below only proves
something if both sides render the same upstream chart version.

Before committing, that script runs `helm lint` and the full Helm and Kustomize
comparison, so a release that changes something the chart configures fails the
synchronization run rather than landing silently.

## Kustomize Mapping

- `ci/values-kubeflow.yaml`: `applications/spark/spark-operator/overlays/kubeflow`

## Comparison

```bash
helm lint applications/spark/spark-operator/helm --namespace kubeflow
python3 tests/run_helm_kustomize_comparison.py spark-operator --all-scenarios
python3 tests/test_spark_operator_helm_chart.py
```

Both sides of that comparison render the same upstream chart, so agreement is
close to tautological. What it proves is narrow but worth having: that the values
in this chart reproduce the flags the synchronization script passes, and that the
three Kubeflow roles survive. It says nothing about whether the upstream chart is
itself correct.
