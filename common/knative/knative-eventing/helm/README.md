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

The Helm-only Kustomize wrapper also omits `spec.replicas` and the controller's
bootstrap environment entries on `Deployment/pingsource-mt-adapter`: the five
`K_*` configuration entries and `POD_NAME`. The two namespace downward references
remain in the controller's order. The comparison descriptor permits only this
exact transformation and compares the remaining Deployment fields, including its
image, service account, probes and restricted security context.

This has one deliberate startup difference: Kubernetes defaults the adapter to
**one idle Pod**, while the distribution's unmodified manifest starts at zero.
The idle adapter uses upstream configuration defaults until the first PingSource
causes the controller to populate its environment. Event delivery still requires
a PingSource. The controller requires the Deployment to exist; Helm continues to
install and remove it. Budget its existing 125m CPU/64Mi memory request even before
creating a source. The source overlay and upstream bundle remain unchanged.

The [pinned PingSource controller](https://github.com/knative/eventing/blob/d6139ffb2175b4a7387f56a8b2c589a17c631719/pkg/reconciler/pingsource/pingsource.go#L159)
replaces that environment and scales the adapter. Reapplying the original
replicas and environment makes Helm 4 server-side apply conflict with `controller`.
Switching to client-side apply also resets this live state, so it is not a fix.

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
./tests/knative_eventing_helm_smoke_test.sh
# Destructive: only on a disposable integration cluster. Requires PyYAML.
./tests/knative_eventing_helm_lifecycle_test.sh
```

The workflow gate requires a fresh, exact PingSource event payload, then
two unchanged upgrades that preserve the adapter specification, generation and
Pod identities, an actual controller Pod-template rollout, compatible rollback,
retained PingSource/EventType identities, the expected conversion interruption,
recovered converted-version reads and fresh delivery after reinstall. This uses
only core Eventing; it does not create a Broker. A controller-template change is
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
