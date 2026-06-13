# Kubeflow Namespaces Helm Chart

This chart renders the Kubeflow-owned namespace foundation resources from `common/kubeflow-namespace/base` and the platform dependency namespaces used by the managed Kubeflow install.

Templates are split by resource type to keep namespace and NetworkPolicy review focused.

It creates:

- `Namespace/kubeflow`
- `Namespace/kubeflow-system`
- `Namespace/cert-manager`
- `Namespace/istio-system`
- `Namespace/oauth2-proxy`
- `Namespace/auth`
- namespace-scoped NetworkPolicies required by the platform baseline

If one of these namespaces already exists, for example a company-managed `cert-manager` namespace, the chart does not recreate or adopt it. Helm does not patch labels on unmanaged pre-existing resources; apply the required labels to that namespace separately if they are missing.

Namespaces created by this chart are kept when the Helm release is uninstalled, because platform namespaces can contain resources owned by later Kubeflow charts.

## Namespace names

All namespace names are fixed to match the Kustomize baseline. They are not configurable.

To opt out of a platform dependency namespace, set `platformNamespaces.<key>.enabled: false` in your values file.

This chart uses Helm `lookup` to detect pre-existing unmanaged namespaces and skip them, so Helm does not try to adopt resources owned outside this release. `helm template` cannot exercise this branch because `lookup` needs a live cluster.

Example smoke check:

```bash
kind create cluster
kubectl create namespace cert-manager

helm install kubeflow-namespaces ./experimental/helm/charts/kubeflow-namespaces --namespace default

kubectl get namespace cert-manager
helm get notes kubeflow-namespaces --namespace default
```

The notes should report `cert-manager` as `skipped-unmanaged`. If the skipped namespace is missing required labels, apply them manually before installing dependent charts.

Install as the bootstrap chart from `default`, because this chart creates `kubeflow-system`:

```bash
helm install kubeflow-namespaces ./experimental/helm/charts/kubeflow-namespaces --namespace default
```

Validate parity with:

```bash
./tests/helm_kustomize_compare.sh kubeflow-namespaces base
./tests/helm_kustomize_compare.sh kubeflow-namespaces platform-namespaces
```
