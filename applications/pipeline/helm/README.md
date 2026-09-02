# Kubeflow Pipelines Helm Chart

This chart renders the current Kubeflow Pipelines Kustomize resources with
Helm. Kustomize remains the source of truth, and the checked-in templates are
generated from the two supported platform scenarios.

## Installation

Install the Kubeflow foundation, cert-manager, Istio, OAuth2-Proxy, Profile
Controller, and required multi-tenancy resources first.

The chart requires its release namespace to be `kubeflow` and refuses to install
anywhere else. Every resource it renders declares `namespace: kubeflow`, so a
release installed elsewhere would store its metadata in one namespace while
modifying another, and `helm uninstall` would then delete resources it does not
appear to own. It does not create that namespace — the `kubeflow-namespaces`
foundation chart does.

Install the scenario CRDs first:

```bash
helm install kubeflow-pipelines ./applications/pipeline/helm \
  --namespace kubeflow \
  --set scenario=platform-database
```

Wait for every CRD rendered by the selected scenario:

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

The CRDs carry `helm.sh/resource-policy: keep` because deleting a Helm release
must not delete cluster APIs and their persisted custom resources.

## Kustomize Mapping

- `platform-database`: `applications/pipeline/overlays`
- `platform-k8s-native`: `applications/pipeline/upstream/env/cert-manager/platform-agnostic-multi-user-k8s-native`

AWS, Google Cloud, MinIO, PostgreSQL, OpenShift, and standalone installation
variants are intentionally deferred.

## Regeneration

Run from the repository root:

```bash
python3 scripts/generate-pipelines-helm-manifests.py
```

The generator renders both supported Kustomize paths, stores identical
resources once, separates CRDs from ordinary resources, and writes
scenario-specific differences under `manifests/`, which small templates load with `.Files.Get`.

## Validation

```bash
python3 tests/pipelines_helm_manifest_generator_test.py
python3 tests/pipelines_helm_chart_test.py
helm lint applications/pipeline/helm
python3 tests/run_helm_kustomize_comparison.py kubeflow-pipelines --all-scenarios
```
