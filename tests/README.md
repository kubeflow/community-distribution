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

## Helm release storage size

Helm stores every release revision in one Kubernetes Secret holding
`base64(gzip(json(release)))`, and the release JSON embeds the whole chart,
including payloads read with `.Files.Get`, next to the rendered manifest.
Kubernetes refuses a Secret above 1,048,576 bytes, so a chart that lints,
packages and renders can still be impossible to install, and a template
switch that renders less does not help. Every chart with a descriptor is
measured for every scenario from a client-generated release record
(`helm install --dry-run=client --output=json`), encoded by the Go helper in
`tests/helm-release-size-encoder` exactly as Helm's storage driver encodes it.

```bash
python3 tests/helm_release_size.py            # every chart, every scenario
python3 tests/helm_release_size.py istio      # one component
python3 tests/helm_release_size_test.py -v    # the guard and its fixtures
```

Rows above 80 % of the limit are reported as warnings; a row above the limit
fails. The record is generated without a cluster: templates that use
`lookup`, generate credentials or certificates, or depend on cluster
capabilities can render differently on a live installation, so the guard does
not replace installing and upgrading the chart on a cluster.

## Generated payload freshness

The Dashboard and Notebooks charts read their resources from committed payloads
under `<chart>/manifests/`, written by `scripts/generate-<component>-helm-manifests.py`
from a local `kustomize build`. Parity compares those payloads semantically, and
the upstream replay reruns a synchronization script only for changed paths it
knows about; neither proves that the committed bytes are the generator's current
output. Every generator therefore has a `--check` mode that renders the local
inputs, compares bytes and file sets with the committed directory, writes
nothing, and exits 1 listing each stale, missing or extra file. The repair is
the generator itself, not the synchronization script, which imports upstream:

```bash
python3 scripts/generate-dashboard-helm-manifests.py --check
python3 scripts/generate-pipelines-helm-manifests.py --check
python3 scripts/generate-notebooks-v1-helm-manifests.py --check
python3 scripts/generate-dashboard-helm-manifests.py        # regenerate
python3 tests/helm_payload_freshness_test.py -v             # the check and its fixtures
```

Continuous integration runs the test in the `Test chart behavior` job for every
generator matching `scripts/generate-*-helm-manifests.py`.

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
| `controllerOwnedWebhookRules` | list exact webhook entry names whose nonempty `rules` are removed only from the Kustomize side; Helm must omit the key entirely, including empty or null values |

`controllerOwnedWebhookRules` is deliberately narrower than resource patterns:
its sole action must target an exact `MutatingWebhookConfiguration/name` or
`ValidatingWebhookConfiguration/name`, with a nonempty reason and unique exact
webhook names. Wildcards and namespace segments are rejected. Both resources must
use `admissionregistration.k8s.io/v1`, and each target webhook must exist exactly
once. Missing or empty baseline rules fail; declaring any Helm rules fails before
empty-value normalization. The allowance fires only when baseline rules are
removed. Other fields, webhook entries and resources still compare normally.

Labels in the `helm.sh/` namespace and annotations in the `helm.sh/` and
`meta.helm.sh/` namespaces are always ignored; they are properties of Helm
itself, not of one chart, so they are not declared per chart.

### Sibling charts and partition groups

A component whose resources form more than one release ships sibling charts
named `helm*` next to its Kustomize sources, for example
`applications/trainer/helm-crds`, `applications/trainer/helm` and
`applications/trainer/helm-runtimes`. Discovery finds every `helm*` directory
holding a `Chart.yaml`; a chart's own `charts/` dependencies are never
discovered as releases of their own.

Sibling charts that split one Kustomize baseline declare the same group name
in `partition`, the same scenario names over the same `kustomize` targets, and
select their share with `onlyKinds` or `excludeKinds`:

```yaml
component: trainer-apis
partition: trainer
scenarios:
  platform:
    kustomize: [applications/trainer/overlays]
    onlyKinds: [CustomResourceDefinition]
```

Selection alone proves nothing about what a release creates, because the
comparison filters both sides: three charts that each render the whole
component would pass three green subset comparisons. The partition check
therefore renders each member's **complete** output, from a temporary copy with
isolated Helm directories, and requires it to be exactly the member's selected
baseline objects: nothing missing, nothing extra, nothing twice, and every
baseline object selected by exactly one member. Objects are identified by API
group, kind, namespace and name; for a kind the baseline's own
`CustomResourceDefinition` declares cluster-scoped, a stray `metadata.namespace`
is not part of the identity. A member cannot `skip` objects or declare
`helmOnlyResources`, cannot ship install-once `crds/` content at any dependency
depth (`helm show crds` on the prepared chart must list nothing), and cannot
render Helm hooks: those mechanisms are outside what the check can prove, so they are
rejected rather than modelled.

```bash
python3 tests/run_helm_kustomize_comparison.py --partitions   # every declared group
python3 tests/comparison_partitions_test.py -v                # the check and its fixtures
```

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
