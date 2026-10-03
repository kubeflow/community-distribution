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
Do not install over an independently managed JobSet or an existing Kustomize
Trainer installation. Matching manifests do not transfer resource ownership to
Helm; migration requires a separately reviewed procedure and is not covered here.

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

Render and storage tests do not establish lifecycle safety. The full Helm
integration workflow runs `tests/trainer_test.sh` after installation, then runs
`tests/trainer_helm_lifecycle_test.sh` after the application tests and before the
Pod Security Standards check, using the same disposable Kind cluster.

The lifecycle script runs one fixed sequence:

1. Change the controller Pod templates, verify the live change, and roll back.
2. Change the catalog image, verify the new TrainJob snapshot and JobSet, and roll
   back without rewriting existing snapshots. These fixture jobs stay suspended;
   this checks configuration resolution, not execution of the changed image.
3. Uninstall and reinstall `trainer-apis`, verifying retention of definitions and
   custom objects, then upgrade the reinstalled release with the unchanged chart.
4. Uninstall and reinstall `trainer-runtimes`, verifying admission while the catalog
   is absent and preservation of administrator and namespaced runtimes.
5. Uninstall and reinstall `trainer`, verifying webhook removal and retained
   resources, then run the existing SDK training test again to prove recovery.

For a manual run, first install all three releases and the platform prerequisites
on a disposable cluster:

```sh
KUBECONFIG=/path/to/disposable.kubeconfig \
  TRAINER_HELM_LIFECYCLE_DISPOSABLE=true \
  ./tests/trainer_helm_lifecycle_test.sh kubeflow-user-example-com
```

The script saves resource identities, snapshots and logs under
`logs/trainer-lifecycle/` before destructive operations and on failure. The
workflow uploads that directory through its existing `logs/` artifact step.
Collection uses Kubernetes request timeouts and does not mask the failing test.
Fixtures remain for diagnosis until the disposable cluster is destroyed; a
failure can leave a release changed or uninstalled. No automatic recovery runs
on failure because it could hide the cause.

This sequence does not establish compatibility across Trainer versions, safe API
schema rollback, or behavior of jobs held before their first runtime snapshot.
Those require separate migration-specific validation.
