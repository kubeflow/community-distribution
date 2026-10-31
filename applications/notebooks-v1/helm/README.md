# Kubeflow Notebooks Helm Chart

This chart renders the current Kubeflow Notebooks v1 Kustomize resources with
Helm. Kustomize remains the source of truth. The synchronization script builds
the platform overlay once and writes deterministic payloads under `manifests/`,
which two small templates load with `.Files.Get`.

Helm does not send `.Files.Get` content through the template renderer, so Go
template delimiters that upstream manifests legitimately contain are emitted
literally. This matters for Notebooks in particular: the Notebook Controller
exists to template pod specifications, so an upstream manifest containing
`{{ ... }}` is a matter of time, and evaluating it as chart code would silently
resolve it to the empty string.

## Install

Install the platform foundation and wrapper charts first.

The chart requires its release namespace to be `kubeflow` and refuses to install
anywhere else. It does not create or own that namespace - the
`kubeflow-namespaces` foundation chart does. Every resource this chart renders
declares `namespace: kubeflow`, so a release installed elsewhere would store its
metadata in one namespace while modifying another.

```bash
helm install kubeflow-notebooks ./applications/notebooks-v1/helm \
  --namespace kubeflow \
  --wait
```

## Configuration

| Value | Default | Purpose |
| --- | --- | --- |
| `scenario` | `platform` | Rendered Kustomize parity scenario. Only `platform` is supported. |
| `customResourceDefinitions.enabled` | `true` | Render the Notebook, PVCViewer and Tensorboard custom resource definitions. |

Values that the Kustomize baseline declares - container images and
`configMapGenerator` inputs across the six sub-components - are **not** exposed
yet. Adding them means rendering the resources that carry them from hand-written
templates, which is a separate change.

## Caveats

The platform Notebooks v1 Kustomize overlay includes Jupyter Web Application, Notebook
Controller, PVC Viewer Controller, Volumes Web Application, Tensorboard Controller, and
Tensorboards Web Application. This chart keeps that grouping for parity.

`notebooks.kubeflow.org`, `pvcviewers.kubeflow.org` and
`tensorboards.tensorboard.kubeflow.org` are rendered from `templates/` and carry
`helm.sh/resource-policy: keep`. This deviates from Helm's documented
recommendation to place custom resource definitions in `crds/`, deliberately:
Helm never upgrades or deletes anything in `crds/`, which would freeze all three
schemas at their first installed version. Rendering them as templates keeps the
schemas upgradeable, while the retention policy stops `helm uninstall` from
deleting existing Notebooks, PVC Viewers and Tensorboards.

Because they are templates rather than `crds/` content, Helm's `--skip-crds`
option has no effect on them. Use `customResourceDefinitions.enabled=false` when
an administrator or another release already owns them.

The aggregated `notebook-controller-kubeflow-notebooks-admin` cluster role ships
no `rules` field, because the Kubernetes RBAC aggregation controller owns
`.rules`. The payload used to ship `rules: []`, and with Helm 4 server-side apply
a plain `helm upgrade` stopped with
`conflict with "clusterrole-aggregation-controller": .rules`. Observed on a
cluster on 2026-09-21 (Helm 4.2.2, Kubernetes 1.36.1, no `--force-conflicts`):
the upgrade from such a release to the corrected chart, an unchanged upgrade and
a rollback between corrected revisions succeeded, and the role kept its rules
throughout.

A chart update does not rewrite the release records that Helm already stored. A
revision stored before the correction still contains `rules: []`. In the same
run, `helm rollback` to such a revision failed with the same conflict and left
the release without a `deployed` revision. An upgrade to the corrected chart
recovered it. Recover with the intended values, then check the release and the
workloads:

```bash
helm upgrade kubeflow-notebooks ./applications/notebooks-v1/helm \
  --namespace kubeflow --wait    # plus the values and flags of the installation
helm status kubeflow-notebooks --namespace kubeflow
kubectl get pods --namespace kubeflow
```

Do not delete release history to work around it.

Regenerate the payloads from the local Kustomize inputs, or verify them
without writing:

```bash
python3 -m pip install pyyaml "ruamel.yaml==0.19.1"
python3 scripts/generate-notebooks-v1-helm-manifests.py
python3 scripts/generate-notebooks-v1-helm-manifests.py --check
```

Import a new upstream release, which also regenerates, through the component
synchronization workflow:

```bash
KUBEFLOW_SYNCHRONIZE_NO_COMMIT=true \
  ./scripts/synchronize-notebooks-v1-manifests.sh
```

Do not edit files under `manifests/` directly. Review a generated payload change
by resource identity and upstream source boundary first, then regenerate and
confirm `git diff` is empty. The replay proves the generator is deterministic; it
cannot tell you whether a new upstream release introduced an unintended webhook,
permission or policy change.

## Kustomize Mapping

- `ci/values-platform.yaml`: `applications/notebooks-v1/overlays/istio`

## Comparison

```bash
helm lint applications/notebooks-v1/helm --namespace kubeflow
python3 tests/run_helm_kustomize_comparison.py kubeflow-notebooks platform
python3 tests/run_helm_kustomize_comparison.py kubeflow-notebooks --all-scenarios
python3 tests/notebooks_helm_chart_test.py
```

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../tests/README.md).
