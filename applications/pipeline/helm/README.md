# Kubeflow Pipelines Helm Chart

> Draft: credential and data-retention configuration is unresolved; not
> administrator-ready. An unchanged `helm upgrade` and a rollback between
> corrected revisions are verified on a cluster for the scenario
> `platform-database`. An upgrade that changes a workload, an upgrade between
> chart or application versions, and every upgrade in the scenario
> `platform-k8s-native` are not yet verified. See [Upgrade](#upgrade),
> [Credentials](#credentials) and
> [Storage and uninstallation](#storage-and-uninstallation).

This chart renders the current Kubeflow Pipelines Kustomize resources with
Helm. Kustomize remains the source of truth. The payloads under `manifests/`
are generated from the two supported platform scenarios, with the two
controlled transforms named under [Regeneration](#regeneration), and small
templates load them with `.Files.Get`. Helm does not evaluate that content as a
template, so Go template delimiters inside upstream manifests are emitted
literally.

The packaged Kubeflow Pipelines release is the `appVersion` of `Chart.yaml`.
The values of the chart are `scenario`, `crds.enabled`, and `install.enabled`.

## Installation

Install the Kubeflow foundation, cert-manager, Istio, OAuth2-Proxy, Profile
Controller, and required multi-tenancy resources first.

The chart requires its release namespace to be `kubeflow` and refuses to install
anywhere else. Every namespaced resource it renders declares `namespace: kubeflow`,
so a release installed elsewhere would store its metadata in one namespace while
modifying another, and `helm uninstall` would then delete resources it does not
appear to own. It does not create that namespace - the `kubeflow-namespaces`
foundation chart does.

Install the CustomResourceDefinitions of the scenario first:

```bash
helm install kubeflow-pipelines ./applications/pipeline/helm \
  --namespace kubeflow \
  --set scenario=platform-database
```

Wait for every CustomResourceDefinition rendered by the selected scenario:

```bash
helm get manifest kubeflow-pipelines --namespace kubeflow |
  awk '
    $0 == "kind: CustomResourceDefinition" {
      custom_resource_definition = 1
      next
    }
    custom_resource_definition && /^  name: / {
      print $2
      custom_resource_definition = 0
    }
  ' |
  while read -r custom_resource_definition_name; do
    kubectl wait --for=condition=Established \
      "crd/${custom_resource_definition_name}" \
      --timeout=120s
  done
```

Upgrade the same release to the complete database scenario:

```bash
helm upgrade kubeflow-pipelines ./applications/pipeline/helm \
  --namespace kubeflow \
  --values ./applications/pipeline/helm/ci/values-platform-database.yaml \
  --wait \
  --timeout 20m
```

For Kubernetes-native pipeline definitions, use
`scenario=platform-k8s-native` during the first command and
`ci/values-platform-k8s-native.yaml` during the upgrade.

`tests/pipelines_helm_install.sh <scenario>` runs the same three steps and then
waits for every Deployment of the release. The scenario argument is required.

## Upgrade

While the payload shipped `rules: []` for the aggregated ClusterRoles
`kubeflow-pipelines-edit` and `kubeflow-pipelines-view`, an unchanged
`helm upgrade` of the installed release failed on these two ClusterRoles with
`conflict with "clusterrole-aggregation-controller": .rules` (observed on
2026-09-20 with Helm 4.2.2 and Kubernetes 1.36.1). The generator now omits that
field, see [Regeneration](#regeneration).

Observed on 2026-09-21 with Helm 4.2.2 and Kubernetes 1.36.1 on a single-node
kind cluster, scenario `platform-database`, every command without
`--force-conflicts`, `--force` or `--take-ownership`:

- On a release that was installed from the payload with `rules: []`, an
  unchanged `helm upgrade` with that same payload failed again with the
  conflict above and left a `failed` revision.
- The upgrade command of [Installation](#installation) with the regenerated
  payload then succeeded on that release. None of the 135 objects of the
  release received a new `resourceVersion`, and no pod was replaced or
  restarted.
- A second, unchanged `helm upgrade` with the regenerated payload succeeded and
  again changed no object.
- `helm rollback` to the revision of the first upgrade with the regenerated
  payload succeeded and changed no object.
- In every one of these states `clusterrole-aggregation-controller` was the
  only owner of `.rules` of both ClusterRoles, and their rules (10 and 4) did
  not change.

Helm keeps the manifests of earlier revisions. A revision that was stored
before the regeneration still contains `rules: []`. `helm rollback` to such a
revision failed with the same conflict. It changed no object of the release,
but it left the newest revision `failed` and no revision in the state
`deployed`. The upgrade command of [Installation](#installation) with the
regenerated payload then succeeded on that release and produced a `deployed`
revision again.

Not verified on a cluster: an upgrade that changes a workload, an upgrade
between two chart versions or two application versions, a rollback that changes
an object, and any upgrade or rollback in the scenario `platform-k8s-native`.

## Credentials

The payload ships the baseline default Secrets `mysql-secret` and
`mlpipeline-minio-artifact`, identical to the Kustomize installation. The
credential interface of this chart is unresolved: the chart has no values for
credentials, and no administrator procedure for other credentials is validated.
Equal Helm and Kustomize renders prove the desired output only. They do not
show how Helm treats a Secret that was changed in the cluster, nor that the
database and the artifact service agree with a changed Secret.

## Storage and uninstallation

`helm uninstall` deletes the chart-owned PersistentVolumeClaims
`mysql-pv-claim` and `seaweedfs-pvc`. Whether the backing data is deleted
depends on the reclaim policy of the PersistentVolume and the StorageClass.
The chart gives no data retention guarantee. With the reclaim policy `Delete`,
observed on a kind cluster with its default `standard` StorageClass, both
PersistentVolumes and their data were deleted together with the claims, and
the reinstalled release started with new volumes and no run or experiment
records.

The CustomResourceDefinitions carry `helm.sh/resource-policy: keep`, so
`helm uninstall` retains the definitions installed by the selected scenario
(14 for `platform-database`, 15 for `platform-k8s-native`), and a later
installation of the same scenario adopts them. Custom resource objects of those
kinds that the release does not render remain, for example the `Workflow`
objects of pipeline runs in a profile namespace. The two custom resource
objects that the release renders, `Application/kubeflow` and
`DecoratorController/kubeflow-pipelines-profile-controller`, are deleted.
Database records and stored artifacts are not protected by that annotation.

Objects that the release does not render also remain after `helm uninstall`:
the Secret `webhook-server-tls`, which cert-manager issues for
`Certificate/kfp-cache-cert`, and the ConfigMaps and the Secret
`mlpipeline-minio-artifact` that the Pipelines profile controller created in
a profile namespace. When the artifact store volume was deleted, that
retained Secret held an access key that the new artifact store did not know.
A pipeline run in the existing profile namespace then failed with
`The access key ID you provided does not exist in our records`, and a run
succeeded again only after that Secret had been deleted and the Pipelines
profile controller had created a new one.

## Kustomize Mapping

- `platform-database`: `applications/pipeline/overlays`
- `platform-k8s-native`: `applications/pipeline/upstream/env/cert-manager/platform-agnostic-multi-user-k8s-native`

AWS, Google Cloud, MinIO, PostgreSQL, OpenShift, and standalone installation
variants are intentionally deferred.

## Regeneration

`scripts/synchronize-pipelines-manifests.sh` imports the upstream release,
regenerates the payloads, and updates `appVersion`. To regenerate the payloads
from the local Kustomize inputs only, run from the repository root:

```bash
python3 scripts/generate-pipelines-helm-manifests.py
```

The generator renders both supported Kustomize paths, stores identical
resources once, separates CustomResourceDefinitions from ordinary resources,
and writes scenario-specific differences under `manifests/`.

The payload resources are those of `kustomize build` with exactly two
controlled transforms, applied when a payload is written:

- Every CustomResourceDefinition gains the annotation
  `helm.sh/resource-policy: keep`.
- Every aggregated ClusterRole loses its empty `rules` field, because the
  aggregation controller owns that field and Helm must not claim it. A
  ClusterRole is aggregated when its API group is `rbac.authorization.k8s.io`
  and its `aggregationRule` has at least one `clusterRoleSelectors` entry; a
  name or a label does not decide it. The `aggregationRule`, the labels, and
  the rules of every contributing ClusterRole are unchanged. Nonempty rules of
  an aggregated ClusterRole fail the generation instead of being discarded. The
  Kustomize baseline keeps `rules: []`, which the comparison treats as equal
  to the omitted field.

To verify that the committed payloads are what the generator produces, without
writing anything:

```bash
python3 scripts/generate-pipelines-helm-manifests.py --check
```

It lists every stale, missing, or extra file, prints the command that repairs
it, and exits with status 1.

## Validation

```bash
python3 scripts/generate-pipelines-helm-manifests.py --check
python3 tests/pipelines_helm_manifest_generator_test.py
python3 tests/pipelines_helm_chart_test.py
python3 tests/pipelines_helm_install_helper_test.py
helm lint applications/pipeline/helm --namespace kubeflow
python3 tests/run_helm_kustomize_comparison.py kubeflow-pipelines --all-scenarios
```
