# Kubeflow Platform Helm Chart

This chart renders the Kubeflow-owned shared platform RBAC resources from `common/kubeflow-roles/base`.

It creates the aggregate `ClusterRole` resources used by Kubeflow platform components:

- `kubeflow-admin`
- `kubeflow-edit`
- `kubeflow-view`
- `kubeflow-kubernetes-admin`
- `kubeflow-kubernetes-edit`
- `kubeflow-kubernetes-view`

Install after `kubeflow-namespaces`, with release metadata stored in `kubeflow-system`:

```bash
helm install kubeflow-platform ./experimental/helm/charts/kubeflow-platform --namespace kubeflow-system
```

Validate parity with:

```bash
./tests/helm_kustomize_compare.sh kubeflow-platform base
```
