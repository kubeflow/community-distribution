# Cert Manager Helm Wrapper Chart

This chart wraps the upstream cert-manager Helm chart and adds the Kubeflow-specific cert-manager resources from `common/cert-manager/overlays/kubeflow`.

It installs:

- upstream cert-manager `v1.20.2`
- cert-manager CRDs
- optional `ClusterIssuer/kubeflow-self-signing-issuer`
- optional Kubeflow cert-manager NetworkPolicies

In the Kubeflow platform install, apply the foundation charts first. The `kubeflow-namespaces` chart provides `Namespace/cert-manager`; this wrapper stores its Helm release metadata in that same workload namespace.

```bash
helm install kubeflow-namespaces ./experimental/helm/charts/kubeflow-namespaces --namespace default
helm install kubeflow-platform ./experimental/helm/charts/kubeflow-platform --namespace kubeflow-system

helm install cert-manager ./experimental/helm/charts/cert-manager --namespace cert-manager --wait
helm upgrade cert-manager ./experimental/helm/charts/cert-manager --namespace cert-manager \
  --values ./experimental/helm/charts/cert-manager/ci/values-kubeflow.yaml --wait
```

The install is split into base install plus upgrade because `ClusterIssuer` cannot be created until cert-manager CRDs are available.

If the cluster already has a company-managed cert-manager installation, disable the upstream dependency, then install only the Kubeflow-specific resources. If `Namespace/cert-manager` already exists, the foundation chart does not recreate or adopt it; apply any required labels separately if they are missing.

```bash
helm install cert-manager ./experimental/helm/charts/cert-manager --namespace cert-manager \
  --values ./experimental/helm/charts/cert-manager/ci/values-existing-cert-manager.yaml --wait
```

In this mode, cert-manager CRDs, webhook, and controllers must already exist.

Validate parity with:

```bash
./tests/helm_kustomize_compare.sh cert-manager base
./tests/helm_kustomize_compare.sh cert-manager kubeflow
./tests/helm_kustomize_compare.sh cert-manager existing
```
