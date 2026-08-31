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
helm install kubeflow-platform ./common/kubeflow-roles/helm --namespace kubeflow-system
```

Validate parity with:

```bash
python3 tests/run_helm_kustomize_comparison.py kubeflow-platform platform-cluster-roles
```

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../tests/README.md).

