# Katib Helm Chart

This chart renders the Katib Kustomize installation of the distribution,
`applications/katib/upstream/installs/katib-with-kubeflow`, with Helm. Kustomize
remains the source of truth. Pinned Katib publishes no Helm chart to wrap, so
the synchronization script builds that installation once and writes
deterministic payloads under `manifests/`, which two small templates load with
`.Files.Get`.

Helm does not send `.Files.Get` content through the template renderer, so Go
template delimiters that an upstream manifest may contain are emitted literally
instead of being evaluated as chart code.

## Prerequisites

Install these first, in this order:

1. the `kubeflow-namespaces` foundation chart, which owns the `kubeflow`
   namespace;
2. cert-manager: the chart renders an `Issuer` and a `Certificate` for the Katib
   webhook;
3. Istio and the Kubeflow Istio resources: the chart renders a `VirtualService`
   on `kubeflow-gateway` and an `AuthorizationPolicy` for the Katib user
   interface.

Experiments run in profile namespaces. A profile namespace needs the label
`katib.kubeflow.org/metrics-collector-injection=enabled`, as
[`tests/katib_helm_install.sh`](../../../tests/katib_helm_install.sh) sets it.

## Install

The chart requires its release namespace to be `kubeflow` and refuses to install
anywhere else. It does not create or own that namespace. Every namespaced
resource this chart renders declares `namespace: kubeflow`, so a release
installed elsewhere would store its metadata in one namespace while modifying
another.

```bash
helm install katib ./applications/katib/helm \
  --namespace kubeflow \
  --wait
```

## Configuration

| Value | Default | Purpose |
| --- | --- | --- |
| `scenario` | `platform` | Rendered Kustomize parity scenario. Only `platform` is supported. |
| `customResourceDefinitions.enabled` | `true` | Render the Experiment, Suggestion and Trial custom resource definitions. |

Values that the Kustomize baseline declares - the three container images and the
`katib-config` `configMapGenerator` input - are **not** exposed yet. Adding them
means rendering the resources that carry them from hand-written templates, which
is a separate change. The other upstream installations (`katib-standalone`,
`katib-cert-manager`, `katib-leader-election`, `katib-standalone-postgres`,
`katib-openshift`, `katib-external-db`) remain available through Kustomize; this
chart does not render them.

## Data and credentials

The chart carries the baseline as it is. **`helm uninstall` deletes the
`katib-mysql` PersistentVolumeClaim and the `katib-mysql-secrets` Secret.**
Whether the volume data survives depends on the reclaim policy of the
PersistentVolume; with `Delete` the recorded trial metrics are lost. The retained
custom resource definitions keep Experiments and Trials, not their metrics in
the database. The chart makes no retention, backup or rotation claim.

The claim requests 10Gi from the default StorageClass, and the MySQL root
password is the fixed value of the upstream manifest, exactly as in the
Kustomize installation.

Experiments and Trials remain after `helm uninstall`. Their finalizers are
removed only by a running Katib controller.

## Caveats

`experiments.kubeflow.org`, `suggestions.kubeflow.org` and `trials.kubeflow.org`
are rendered from `templates/` and carry `helm.sh/resource-policy: keep`. This
deviates from Helm's documented recommendation to place custom resource
definitions in `crds/`, deliberately: Helm never upgrades or deletes anything in
`crds/`, which would freeze all three schemas at their first installed version.
Rendering them as templates keeps the schemas upgradeable, while the retention
policy stops `helm uninstall` from deleting existing Experiments. Retention does
not protect against rolling back to an incompatible schema.

Because they are templates rather than `crds/` content, Helm's `--skip-crds`
option has no effect on them. Use `customResourceDefinitions.enabled=false` when
an administrator or another release already owns compatible definitions. Taking
over definitions that another tool created is not supported.

The aggregated `kubeflow-katib-admin` cluster role ships no `rules` field,
because the Kubernetes RBAC aggregation controller owns `.rules`. With Helm 4
server-side apply an explicit `rules: []` makes every later `helm upgrade` stop
with `conflict with "clusterrole-aggregation-controller": .rules`.

## Maintenance

Regenerate the payloads from the local Kustomize inputs, or verify them without
writing:

```bash
python3 -m pip install pyyaml "ruamel.yaml==0.19.1"
python3 scripts/generate-katib-helm-manifests.py
python3 scripts/generate-katib-helm-manifests.py --check
```

Import a new upstream release, which also regenerates, through the component
synchronization workflow:

```bash
KUBEFLOW_SYNCHRONIZE_NO_COMMIT=true \
  ./scripts/synchronize-katib-manifests.sh
```

The distribution deviates from upstream in one imported file,
`applications/katib/upstream/components/mysql/mysql.yaml`. The synchronization
script reapplies that deviation from
[`../patches/mysql-image-and-probes.patch`](../patches/mysql-image-and-probes.patch)
and checks the imported file and the result by SHA-256. When upstream changes
that file the script stops; review the patch, then update it together with both
digests in the script.

Do not edit files under `manifests/` directly. Review a generated payload change
by resource identity and upstream source boundary first, then regenerate and
confirm `git diff` is empty.

## Kustomize Mapping

- `ci/values-platform.yaml`: `applications/katib/upstream/installs/katib-with-kubeflow`

## Comparison

```bash
helm lint applications/katib/helm --namespace kubeflow
python3 tests/run_helm_kustomize_comparison.py katib --all-scenarios
python3 tests/katib_helm_chart_test.py
```

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../tests/README.md).
