# Knative Eventing core for Kubeflow

One independent release installs the v1.23.0 distribution security overlay,
`common/knative/knative-eventing/overlays/security`: 105 objects including 17 API
definitions. It does not require a Serving release, install the Knative Operator,
or enable the downloaded but disabled in-memory channel and MT-channel broker
bundles. The supported `platform` scenario means Eventing core, including direct
PingSource-to-Service delivery. Broker/channel installations need their own
explicit baseline and support decision.

## Installation and configuration

Use Helm 4.2.2 after installing the foundation `kubeflow` Namespace. Commands run
from the distribution repository root:

```sh
./tests/knative_eventing_helm_install.sh
```

The `knative-eventing` release record lives in `kubeflow`; another release namespace
is rejected. The component owns and retains its `knative-eventing` Namespace with
the source's restricted Pod Security labels. The foundation does not own it.

The installer first renders `installation.phase=definitions`, waits for all CRDs
to become Established, then explicitly upgrades with reset values to the default
`installation.phase=complete`. It resumes an interrupted definitions phase forward;
complete releases never go back to definitions. Do not choose the bootstrap phase
on an existing complete release: omitted controllers would be pruned.

The chart has no unrestricted patch or upstream-values interface. Configuration
comes from the distribution's overlay and generated payloads. It applies two
shared, reviewed transforms: CRD retention and omission of controller-owned empty
`rules` on five aggregated ClusterRoles. Rules on ordinary ClusterRoles remain
untouched. Most resources use literal `.Files.Get` payloads; only the retained
Namespace is a hand-written, parity-checked template.

### PingSource adapter ownership

The chart is generated directly from the distribution's security overlay. Both
installation paths omit `spec.replicas` and the PingSource controller's bootstrap
environment entries on `Deployment/pingsource-mt-adapter`. The controller supplies
its runtime configuration when a PingSource is reconciled. Helm continues to
install and remove the Deployment, which the controller requires to exist.

Kubernetes starts one idle adapter Pod, requesting 125m CPU and 64Mi memory,
before the first PingSource exists. The controller does not scale it back to zero
when the last source is deleted. See the [shared ownership and Kustomize upgrade
notes](../../README.md#pingsource-adapter-ownership).

The [pinned PingSource controller](https://github.com/knative/eventing/blob/d6139ffb2175b4a7387f56a8b2c589a17c631719/pkg/reconciler/pingsource/pingsource.go#L159)
replaces that environment and scales the adapter. Reapplying the original
bootstrap fields conflicts with its ownership under Helm 4 server-side apply.

## Lifecycle and API conversion

```sh
helm upgrade knative-eventing common/knative/knative-eventing/helm -n kubeflow --reset-values --set installation.phase=complete --wait --timeout 10m
helm history knative-eventing -n kubeflow
helm rollback knative-eventing COMPLETE_REVISION -n kubeflow --wait --timeout 10m
helm uninstall knative-eventing -n kubeflow --wait --timeout 10m
```

All 17 CRDs are rendered through templates with `helm.sh/resource-policy: keep`:
upgrades manage schemas; uninstall preserves definitions, custom resources and
the component Namespace. It removes controllers and services. Event delivery and
reconciliation stop. A kept definition is not a promise that every API version
remains usable: PingSource (`v1` storage, `v1beta2` converted) and EventType
(`v1beta2` storage, `v1beta1`/`v1beta3` converted) require the removed
`eventing-webhook` service for conversion. Restore the same release name and
namespace before expecting converted-version operations or delivery to recover.
The reinstall creates a new webhook certificate. Ready webhook Pods do not prove
that the API server has picked up the corresponding trust configuration; check
converted-version operations before resuming clients that depend on them.

Only a previously complete, schema-compatible revision is an operational rollback
target. Bootstrap revisions and schema downgrades have different risks. Never
use routine `--force-conflicts` or transfer definitions to a second field manager
to conceal an ownership conflict. Automatic adoption from another release or
Kustomize installation is not supported by this draft.

A stored revision from before the adapter-ownership correction still contains
the conflicting fields. Do not roll back to that revision after a PingSource has
reconciled: it can fail and leave no revision marked deployed. Upgrade forward
with the fixed chart, complete phase and the same release name/namespace to
recover. Do not use `--force-conflicts` to make the old revision win.

After a supported version upgrade and healthy controllers, the administrator can
explicitly run the separately synchronized migration Job:

```sh
kubectl delete job storage-version-migration-eventing -n knative-eventing --ignore-not-found
kubectl apply -k common/knative/knative-eventing-post-install-jobs/base
kubectl wait --for=condition=complete job/storage-version-migration-eventing -n knative-eventing --timeout=10m
```

The fixed-name Job has a 600-second TTL and is not an install/uninstall hook. Check
Knative's version-specific upgrade guidance before modifying stored API versions.
The request-reply StatefulSet has no persistent volume in this baseline; this
chart adds no durability guarantees beyond the distribution's resources.

## Validation and draft boundaries

```sh
python3 scripts/generate-knative-eventing-helm-manifests.py --check
helm lint common/knative/knative-eventing/helm -n kubeflow
python3 tests/run_helm_kustomize_comparison.py knative-eventing --all-scenarios
python3 tests/knative_eventing_helm_chart_test.py
python3 tests/helm_release_size.py knative-eventing
# Non-destructive: one fresh PingSource delivery, no Helm operation.
./tests/knative_eventing_helm_lifecycle_test.sh --smoke-only
# Destructive: only on a disposable cluster that no other test needs. Requires PyYAML.
./tests/knative_eventing_helm_lifecycle_test.sh
```

The script creates one receiver and PingSource and requires a fresh, exact
PingSource event payload. With `--smoke-only` it stops there; the full Helm
integration workflow runs this mode, which does not validate the lifecycle.

Without an argument, the script continues with the release lifecycle. The
`knative_eventing_helm_lifecycle` job in `.github/workflows/knative_test.yaml`
runs it on its own cluster with only the foundation namespaces and Eventing
installed. It reuses the receiver and PingSource for fresh event checks after
each Helm operation and requires
two unchanged upgrades that preserve the adapter specification, generation and
Pod identities, a controller Pod-template change observed on the live Deployment,
a compatible rollback that restores the live Pod template,
retained PingSource/EventType identities, the expected conversion interruption,
recovered converted-version reads and fresh delivery after reinstall. This uses
only core Eventing; it does not create a Broker. After reinstall, it retries each
converted API for 120 seconds, with a 10-second timeout per request.
It saves diagnostics before each upgrade phase, rollback and uninstall, the
adapter snapshots and the conversion errors under
`logs/knative-eventing-lifecycle/`, which the workflow uploads, and preserves
fixtures and failure diagnostics when a check fails. A controller-template change is
not proof of cross-version schema downgrade safety.

Local parity, chart behavior and release-size tests do not establish these live
properties. Keep the pull request a draft until the clean-install and full live
lifecycle gates have passed and their evidence is recorded. This implementation
makes no claim that its cluster scripts have already run.

The shared Knative synchronizer updates both components from their own pinned
bundles, regenerates their payloads, lints them and stages only generated outputs.
For local overlay changes, regenerate without downloading or committing:

```sh
python3 scripts/generate-knative-eventing-helm-manifests.py
```
