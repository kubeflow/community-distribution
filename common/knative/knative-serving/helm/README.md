# Knative Serving for Kubeflow

This chart installs the distribution's patched Serving and net-istio v1.23.0
bundles. It does not install the Knative Operator. The `platform` default equals
`kustomize build common/knative/knative-serving/overlays/gateways`, except for
Helm retention annotations and the two controller-owned admission rule fields
described below. Most resources are generated literal payloads; the
Namespace and two bootstrap consumers are small parity-checked templates.

## Prerequisites and installation

Use Helm 4.2.2. Install the Kubeflow namespace, Certificate Manager, Istio,
cluster-local gateway, and Kubeflow Istio resources first. The Istio release owns
those gateways. Run all commands from the distribution repository root:

```sh
./tests/knative_serving_helm_install.sh
```

The Helm release `knative-serving` stores its history in `kubeflow`. This chart
owns the `knative-serving` Namespace, preserves its distribution labels, and
retains it on uninstall. Installing the release in another namespace fails.
Namespace retention avoids destroying any objects an administrator added there.

The installer uses one release with three explicit phases:

1. `installation.phase=definitions`: Namespace and 12 retained CRDs; wait for
   their `Established` condition.
2. `installation.phase=controllers`: add controllers, services, admission
   configurations and networking; wait for the webhook Deployments and active
   defaulting/validation admission before creating consumers.
3. `installation.phase=complete` (default): add the queue-proxy Image and internal
   routing Certificate after their APIs and admission controllers are available.

These phases are bootstrap mechanics, not selectable product installations.
Never set a running release back to `definitions` or `controllers`: Helm would
remove previously rendered resources. Existing complete releases use a direct complete upgrade. The installer reads
the saved phase and resumes interrupted bootstrap forward, with explicit reset
values on each upgrade; it never infers readiness merely from release existence.
Unknown saved phases fail for operator inspection.

### Admission ownership

Knative computes admission rules from its registered resource handlers. The chart
omits only `webhooks[name=webhook.serving.knative.dev].rules` in
`MutatingWebhookConfiguration/webhook.serving.knative.dev` and
`webhooks[name=validation.webhook.serving.knative.dev].rules` in
`ValidatingWebhookConfiguration/validation.webhook.serving.knative.dev`.
The [defaulting reconciler](https://github.com/knative/pkg/blob/521cb33b33dd/webhook/resourcesemantics/defaulting/defaulting.go#L239)
and [validation reconciler](https://github.com/knative/pkg/blob/521cb33b33dd/webhook/resourcesemantics/validation/reconcile_config.go#L208)
own these fields. Applying the initial static rules again conflicts under Helm 4
server-side apply after those controllers have replaced them.

The two checked patches live only in this chart's Kustomize wrapper; the
distribution overlay and upstream imports remain unchanged. The comparison
descriptor names each exception and rejects even empty Helm `rules`, while all
other fields remain compared. `failurePolicy: Fail` and `timeoutSeconds: 10`
remain unchanged. The other controller-populated fields were already omitted.

The installer waits for rules, certificate bundles and the expected Service
paths, then uses server-side dry runs to prove defaulting occurs and validation
rejects a negative minimum scale. A failed check stops before the complete
phase. Initial bootstrap and reinstall are maintenance operations: do not submit
concurrent Knative workloads until this gate succeeds. Omitted rules alone do
not match requests, even with `failurePolicy: Fail`.

There is no generic patch interface. The queue-proxy digest is synchronized from
upstream into chart metadata, and must equal the generated `config-deployment`
image. It is not a separate administrator override. Changing distribution
configuration requires a source overlay change followed by regeneration and
parity tests.

## Upgrade, rollback and removal

```sh
helm upgrade knative-serving common/knative/knative-serving/helm -n kubeflow --reset-values --set installation.phase=complete --wait --timeout 10m
helm history knative-serving -n kubeflow
# Choose a previously complete revision at a compatible Knative version.
helm rollback knative-serving COMPLETE_REVISION -n kubeflow --wait --timeout 10m
helm uninstall knative-serving -n kubeflow --wait --timeout 10m
```

Definitions are rendered through templates with `helm.sh/resource-policy: keep`,
so upgrades can update schemas while uninstall leaves definitions and user
objects. The component Namespace is retained too. Controllers, webhooks, routes
and availability are not retained. Removal interrupts reconciliation and serving;
retention is not a zero-downtime or backup guarantee. Reinstall using the same
release name and release namespace. Existing ownership metadata is not adopted
from an unrelated release or Kustomize installation automatically.

Only rollback to a **complete**, schema-compatible revision created with the
admission-rule omission. A stored pre-fix revision still contains static rules
and can fail with an ownership conflict; recover by upgrading with this fixed
chart, not by repeatedly rolling back to that revision. Bootstrap revisions
omit controllers or consumers and are not operational rollback targets. Never
use routine `--force-conflicts`; investigate the field owner. CRD/schema downgrade
and existing workload recovery require lifecycle evidence before release approval.

The separately synchronized storage-version migration Job remains an explicit
administrator step after a supported version upgrade and healthy controllers:

```sh
kubectl delete job storage-version-migration-serving -n knative-serving --ignore-not-found
kubectl apply -k common/knative/knative-serving-post-install-jobs/base
kubectl wait --for=condition=complete job/storage-version-migration-serving -n knative-serving --timeout=10m
```

The Job has a fixed name and a 600-second TTL. Delete its previous completed Job
before deliberately rerunning it. It is not an install/uninstall hook. Check
Knative's version-specific upgrade guidance before changing stored API versions.

## Validation and draft boundaries

```sh
python3 scripts/generate-knative-serving-helm-manifests.py --check
helm lint common/knative/knative-serving/helm -n kubeflow
python3 tests/run_helm_kustomize_comparison.py knative-serving --all-scenarios
python3 tests/knative_serving_helm_chart_test.py
python3 tests/helm_release_size.py knative-serving
./tests/knative_serving_helm_admission_test.sh
./tests/knative_serving_helm_smoke_test.sh kubeflow-user-example-com
# Destructive; use only a disposable cluster that no other test needs. Requires PyYAML.
./tests/knative_serving_helm_lifecycle_test.sh kubeflow-user-example-com
```

The Helm integration workflow installs this chart and tests a real Knative Service
through the cluster-local gateway, requiring its exact response body and rejecting
an unauthenticated request. Existing KServe tests remain in that workflow. It
retains the bootstrap installation, which advances its phases with Helm upgrades,
and one routing probe; the post-installation release lifecycle checks run in the
`knative_serving_helm_lifecycle` job in `.github/workflows/knative_test.yaml`.
That job uses its own cluster, with the Helm foundation charts, a Profile and
this chart, and without KServe. It keeps the Service identity through an
unchanged upgrade, a disposable controller Pod-template change, rollback,
uninstall and reinstall. It verifies admission after the unchanged upgrade, the
live controller annotation after the changed upgrade and the rollback, and
routing with the missing-token rejection after initial installation, the changed
upgrade, the rollback and the reinstall. It saves diagnostics before the
upgrades, the rollback and the uninstall under `logs/knative-serving-lifecycle/`,
which the workflow uploads, and preserves the fixture when a check fails.
That changed-rollout fixture is not evidence for cross-version schema downgrade.
Local chart tests and parity do not prove live installation. Before promoting the
draft, record clean installation, unchanged upgrade, a compatible changed
configuration upgrade and rollback, a retained user Service across uninstall and
same-name reinstall, recovered route traffic and healthy webhook certificates.
No cluster lifecycle result is claimed by the chart implementation alone.

Synchronization downloads the pinned bundles, updates chart metadata, regenerates
payloads, and lints the chart. It stages only generated component outputs.
Regenerate local overlay changes without downloading or committing:

```sh
python3 scripts/generate-knative-serving-helm-manifests.py
```
