# Trainer Helm installation

The default Kubeflow platform installation uses three releases, all recorded in
`kubeflow-system`. The foundation chart must already own that namespace.

| Chart | Release | Owned resources |
| --- | --- | --- |
| `../helm-crds` | `trainer-apis` | Four Trainer and JobSet definitions, retained on uninstall |
| `.` | `trainer` | 35 control-plane resources, including Trainer and JobSet controllers, webhooks and permissions |
| `../helm-runtimes` | `trainer-runtimes` | Eight default ClusterTrainingRuntime objects |

The source is `applications/trainer/overlays`, synchronized from Trainer v2.3.0.
The upstream chart changes controller names/selectors and installs runtimes with
imperative hooks. These charts instead preserve the distribution baseline using
shared generated payloads and ordinary resources. This first implementation
supports the platform default only. Existing external JobSet ownership, data cache,
optional runtime selection and arbitrary controller settings are not supported.
Do not install over an independently managed JobSet installation.

## Prerequisites and installation

Use Helm 4, kubectl, and the foundation-owned `kubeflow-system` namespace.
Use the distribution's other platform prerequisites before the SDK integration
test. These charts do not own user Profiles, user namespaces or training jobs.

From the repository root:

```sh
./tests/trainer_helm_install.sh
./tests/trainer_test.sh kubeflow-user-example-com
```

The installer installs the API release, waits for all four definitions to become
Established, installs both controllers, waits for webhook certificate authority
bundles and service endpoints, and installs the runtime catalog last. It preserves
the existing JobSet restart workaround. Endpoint and certificate readiness do not
prove successful admission: the SDK TrainJob integration test is required.

Without `TRAINER_APIS_CHART` the installer installs `trainer-apis` from the
directory `applications/trainer/helm-crds`, as the workflow does. Set the variable
to install that release from the packaged parent, or from another chart path,
instead; the installer fails before its first command when the path does not exist.
The other two releases and the order do not change.

```sh
helm package applications/trainer/helm-crds --destination /path/to/packages
TRAINER_APIS_CHART=/path/to/packages/trainer-apis-0.1.0.tgz ./tests/trainer_helm_install.sh
```

Arguments name the releases to install, for example
`./tests/trainer_helm_install.sh trainer` after `helm uninstall trainer`. A named
release is installed with the same commands and readiness waits as in the complete
installation, and several named releases keep the order above.

There are three releases, not three revisions of one release. The API chart's
internal dependency is packaging only and must not be installed separately.

## Updates and recovery

Review the complete schema/controller/runtime compatibility before an update.
For additive schemas compatible with the currently running controllers, upgrade
`trainer-apis` first, wait for Established, upgrade `trainer`, wait for controller
and webhook readiness, then upgrade `trainer-runtimes` if its catalog changes.
An incompatible API change requires its own migration plan; no general version
skew guarantee is implied.

```sh
helm upgrade trainer-apis applications/trainer/helm-crds --namespace kubeflow-system --wait --timeout 5m
helm upgrade trainer applications/trainer/helm --namespace kubeflow-system --wait --timeout 10m
helm upgrade trainer-runtimes applications/trainer/helm-runtimes --namespace kubeflow-system --wait --timeout 5m
```

These are individual commands, not a substitute for the readiness and compatibility
checks above. Roll back only the selected release to a tested compatible revision.
A controller rollback does not roll back APIs or the catalog. A retained definition
can still be overwritten by rollback of the API release: `keep` is deletion
retention, not schema downgrade protection. Never perform an incidental API rollback
as part of controller recovery. Runtime rollback restores the catalog objects; it
does not rewrite snapshots already captured by existing TrainJobs.

Aggregated ClusterRoles omit their empty `rules` field so the Kubernetes
aggregation controller owns effective permissions. Contributing roles and selectors
remain unchanged. Do not use routine `--force-conflicts` to bypass upgrade failures.
A stored revision from before this correction may restore the conflicting field;
rollback to it requires a separate reviewed recovery procedure.

## Deletion and ownership

Pause new submissions and account for existing jobs before planned control-plane
downtime. `helm uninstall trainer --namespace kubeflow-system` removes the
controllers and their webhook configurations, but does not remove APIs, the
separate runtime catalog, user TrainJobs or the shared namespace. Retained objects
do not imply admission, reconciliation or workload recovery during downtime.
Reinstall using the same documented release identity and verify admission plus a
new completed TrainJob before resuming submissions.

Before deleting catalog entries or running
`helm uninstall trainer-runtimes --namespace kubeflow-system`, inventory TrainJobs
across all namespaces, including queued and suspended jobs:

```sh
kubectl get trainjobs --all-namespaces -o json
kubectl get clustertrainingruntimes -o yaml
```

Inspect each job's `spec.runtimeRef` and determine whether it references an entry
being removed. Trainer v2.3.0 saves a runtime snapshot on first reconciliation,
but admission still checks the live runtime on subsequent validated job updates.
Removing a referenced runtime may reject suspend/resume updates; a new job may
not yet have a snapshot. Keep required runtime entries until their consumers have
migrated. Helm does not enforce this preflight. Catalog uninstall deletes only its
ordinary owned runtime objects; administrator-created runtimes with other names,
TrainJobs and snapshots are not release resources and are not selected for pruning.

The API release deliberately uses retained templated definitions rather than
Helm's install-once `crds/` directory, allowing explicit schema upgrades.
`helm uninstall trainer-apis --namespace kubeflow-system` retains all four
CRDs and their objects, leaving the definitions outside an active release.
Recover with the same `trainer-apis` release and namespace after verifying
ownership and schema compatibility. Do not use blanket `--take-ownership`.
Actual CRD deletion is a separate destructive decommission action after a
cluster-wide consumer inventory and backup; it deletes stored custom objects.

## Generation and validation

Never hand-edit `manifests/` or the internal API dependency's payloads. Regenerate
and review the resulting deterministic diff:

```sh
python3 scripts/generate-trainer-helm-manifests.py
python3 scripts/generate-trainer-helm-manifests.py --check
python3 tests/run_helm_kustomize_comparison.py --partitions
python3 tests/helm_release_size.py trainer-apis
python3 tests/helm_release_size.py trainer
python3 tests/helm_release_size.py trainer-runtimes
helm lint applications/trainer/helm-crds --namespace kubeflow-system
helm lint applications/trainer/helm --namespace kubeflow-system
helm lint applications/trainer/helm-runtimes --namespace kubeflow-system
```

The three partition descriptors prove that the combined renders own the full
baseline exactly once. Generated bytes are deterministic; documented transformations
are CRD retention annotations and omission of aggregated-role empty rules. Release
storage is measured for each installable chart, including the packaged API parent.
The APIs are kept in a dependency to reduce the stored release size; archive size
alone is not the Kubernetes Secret storage limit.

Render, storage and installer-order tests do not establish lifecycle safety.
Before publishing this chart as ready for use, validate schema retention and
same-owner recovery, controller upgrade/rollback and uninstall/reinstall, runtime
snapshot update/rollback/retirement behavior, and successful SDK training through
this Helm installation path on a disposable cluster.

The lifecycle test is opt-in and requires an explicit kubeconfig for a disposable
cluster that already has the three releases. Arguments after the profile namespace,
or `TRAINER_HELM_LIFECYCLE_SCENARIOS`, select scenarios. Without a selection only
`smoke` runs, which changes no release; `all` runs every scenario in this order:

```sh
KUBECONFIG=/path/to/disposable.kubeconfig \
  TRAINER_HELM_LIFECYCLE_DISPOSABLE=true \
  ./tests/trainer_helm_lifecycle_test.sh kubeflow-user-example-com smoke fixtures
```

| Scenario | Release operation | A pass proves |
| --- | --- | --- |
| `smoke` | none | Admission denies an absent runtime and admits `torch-distributed`; an SDK TrainJob completes |
| `fixtures` | none | A namespaced TrainingRuntime and its TrainJob are admitted; every fixture TrainJob owns a runtime snapshot and a JobSet |
| `controller-upgrade-rollback` | `trainer` upgrade with a changed Pod template, rollback | Rollout and rollback, then admission and a completed SDK TrainJob |
| `controller-reinstall` | `trainer` uninstall, installation | Webhook configurations leave with the release, APIs and catalog stay, then admission and a completed SDK TrainJob |
| `api-upgrade` | `trainer-apis` upgrade with one more optional TrainJob property, upgrade back | The property is served, existing objects stay readable, a new TrainJob is admitted and reconciled |
| `api-reinstall` | `trainer-apis` uninstall, installation, unchanged upgrade | Definitions and objects are retained; the same release name takes the definitions back and manages them again |
| `catalog-update-rollback` | `trainer-runtimes` upgrade with a changed `torch-distributed` image, rollback | The snapshot and the JobSet of a new TrainJob hold the update, the earlier snapshot keeps its content, the rollback restores the live runtime |
| `retirement-after-snapshot` | `trainer-runtimes` uninstall, installation | With a snapshot, admission denies a validated update while the runtime is absent |
| `retirement-before-snapshot` | `trainer-runtimes` uninstall, installation | The admission question only: without a snapshot and a JobSet, admission denies a validated update and a new submission while the runtime is absent |

Every scenario except `smoke` creates an administrator ClusterTrainingRuntime, a
namespaced TrainingRuntime and two suspended TrainJobs, and asserts their UIDs, the
UIDs of their snapshots and JobSets, the snapshot contents, the four definitions
and `kubeflow-system` after every release operation. Object names carry a run
identifier, an existing name is refused, and only objects that the run has created
are deleted. Every installation is a call of `tests/trainer_helm_install.sh` with
the release name, and no command passes a force option. The TrainJob of
`retirement-before-snapshot` is held without a snapshot by
`spec.managedBy: kueue.x-k8s.io/multikueue`, so that scenario shows admission, not
the reconciliation failure of a TrainJob that the Trainer controller manages.
`spec.managedBy` is immutable: that TrainJob cannot be returned to the Trainer
controller and resumed. Only a successful read that returns nothing counts as
absence. The snapshot and the JobSet of the held TrainJob are read through a
bounded window, while the runtime is absent and at the end; a failed read fails
the scenario, and an unreadable Kueue definition refuses it. The `api-upgrade`
scenario proves one additive change, not compatibility between Trainer versions. A
failed scenario can leave a release uninstalled, upgraded to a temporary copy or
rolled back; use only a disposable cluster.

The catalog update is partly covered: every TrainJob stays suspended, so a snapshot
and a JobSet show that the configuration is resolved, not that a resumed TrainJob
runs with it. No scenario runs `helm rollback trainer-apis`; nothing here supports
a claim that it is safe. The lifecycle evidence so far comes from a minimal
single-node kind cluster without Istio.

`tests/trainer_helm_lifecycle_control_flow_test.py` runs the lifecycle test and the
installer without a cluster, against `tests/trainer_helm_lifecycle_fake_cluster.py`
as `helm` and `kubectl`: scenario selection, call order, reinstallation through
the installer, no force option, deletion of owned objects only, and that a failed
read never counts as absence. It does not replace a run on a cluster.
