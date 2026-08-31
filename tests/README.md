# Tests

The scripts in this directory replicate typical user scenarios on a Kind
cluster, and compare every Helm chart against its Kustomize baseline.

## Helm/Kustomize comparison

The contract in one sentence: **a chart must render the same resources as the
Kustomize baseline it wraps, and every intended difference must be declared and
justified.** The harness compares rendered snapshots; runtime behavior, such as
whether a configuration change restarts consuming Pods, belongs to each
component's chart behavior tests.

```bash
python3 tests/run_helm_kustomize_comparison.py --list
python3 tests/run_helm_kustomize_comparison.py dex
python3 tests/run_helm_kustomize_comparison.py istio crds
python3 tests/run_helm_kustomize_comparison.py katib --all-scenarios
python3 tests/run_helm_kustomize_comparison.py all
```

Continuous integration runs one blocking `Compare <component>` job per chart
and pins the Helm version; check `helm version --short` against the version in
`.github/workflows/helm-kustomize-comparison.yml` before treating a local
failure as real.

## The comparison descriptor: `<chart>/ci/comparison.yaml`

Components are discovered, not registered. Every chart declares how it is
compared in its own `ci/comparison.yaml`; adding a chart touches only that
chart's directory, and a chart without a descriptor fails
`tests/comparison_descriptors_test.py`.

### Identity fields

| field | meaning |
| --- | --- |
| `component` | the name used on the command line and in the job matrix |
| `releaseName` | passed to `helm template`; recorded because rendered `matchLabels` embed it, so renaming a release is not a cosmetic change |
| `namespace` | passed to `helm template --namespace` |
| `includeCustomResourceDefinitions` | adds `--include-crds` to the render |
| `dependencyRepositories` | `name: url` map of Helm repositories to add before `helm dependency build` |
| `defaultScenario` | the scenario compared when none is named; may be omitted when the chart declares exactly one |
| `helmUsesKustomizeNameHashes` | default `true`. Set `false` when the chart names ConfigMaps and Secrets without Kustomize's ten-character content-hash suffix, so the hash is stripped from the Kustomize side only. Stripping it from both sides would truncate a legitimate name segment such as `dashboard-parameters`. |

### Scenarios

A scenario pairs one values file with the Kustomize build output it must equal.
A scenario may list several Kustomize directories because Kustomize composes an
installation from directories while Helm selects it with one values file; the
builds are concatenated in order.

```yaml
scenarios:
  platform-full:
    kustomize:
    - common/istio/istio-crds/base
    - common/istio/istio-namespace/base
    - common/istio/istio-install/overlays/oauth2-proxy
    values: ci/values-platform-full.yaml
    # onlyKinds / excludeKinds partition one chart output between scenarios
    # that own different resource subsets. See kubeflow-namespace.
```

### Declared allowances

An allowance names an intended difference between the two sides. The harness
enforces three rules, in this order of importance:

1. **An allowance that matches nothing in any scenario fails the run.** A
   stale allowance is indistinguishable from a wrong one; both are silent.
2. **Every allowance carries a non-empty `reason`.** The reason is the review
   surface: it must say why the difference is intended, not what the rule does.
3. **An allowance names what it allows.** `knownDifferences` and
   `helmOnlyResources` name resources, as `Kind/name` (any namespace, the form
   for cluster-scoped resources) or `Kind/namespace/name`, with `*` wildcards
   per segment; `ignoredLabels` names label keys; retained definitions are
   named individually.

| field | meaning |
| --- | --- |
| `ignoredLabels` | entries of `keys`, label keys ignored on both sides in every resource's top-level metadata; an entry adds `podTemplates: true` when the chart also writes the keys into workload template metadata |
| `knownDifferences` | entries of either `skip` (exclude one named resource from the comparison entirely) or `resource` plus one or more actions below |
| `helmOnlyResources` | resources the chart renders that no Kustomize baseline contains |
| `retainedCustomResourceDefinitions` | a `reason` plus the `names` of the CustomResourceDefinitions the chart annotates `helm.sh/resource-policy: keep`; an undeclared keep annotation fails the comparison, because that annotation makes `helm uninstall` leave the definition and its objects behind |

`knownDifferences` actions:

| action | meaning |
| --- | --- |
| `ignorePodTemplateAnnotations` | ignore the listed pod template annotation keys, typically rollout checksums that replace Kustomize's content-hashed names |
| `compareDataAsYaml` | parse the listed `data` keys as YAML before comparing, so quoting style does not matter |

Labels in the `helm.sh/` namespace and annotations in the `helm.sh/` and
`meta.helm.sh/` namespaces are always ignored; they are properties of Helm
itself, not of one chart, so they are not declared per chart.

### Adding a chart

1. Write `<chart>/ci/comparison.yaml` with the identity fields and one
   scenario per supported installation.
2. Run `python3 tests/run_helm_kustomize_comparison.py <component> --all-scenarios`.
3. For every reported difference, either fix the chart or declare the
   difference with a reason a reviewer can judge.
4. Declare nothing in advance: a declaration that never fires fails the run.

The load-time rejection messages come from `tests/run_helm_kustomize_comparison.py`
and name the file and the rule that was violated; `tests/comparison_descriptors_test.py`
exercises each one.
