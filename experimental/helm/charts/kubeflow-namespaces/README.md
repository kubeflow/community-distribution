# Kubeflow Namespaces Helm Chart

This chart renders the Kubeflow-owned namespace foundation resources from `common/kubeflow-namespace/base`.

Templates are split by resource type to keep namespace and NetworkPolicy review focused.

It creates:

- `Namespace/kubeflow`
- `Namespace/kubeflow-system`
- namespace-scoped NetworkPolicies required by the platform baseline

Install as the bootstrap chart from `default`, because this chart creates `kubeflow-system`:

```bash
helm install kubeflow-namespaces ./experimental/helm/charts/kubeflow-namespaces --namespace default
```

Validate parity with:

```bash
./tests/helm_kustomize_compare.sh kubeflow-namespaces base
```
