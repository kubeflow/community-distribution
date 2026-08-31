# KServe Models Web Application Helm Chart

This Helm chart deploys the KServe Models Web Application into the `kserve`
namespace and preserves Kubeflow routing through
`kubeflow/kubeflow-gateway`.

The chart does not create `Namespace/kserve`. Install the
`kubeflow-namespaces` foundation chart first, or create and label the namespace
through another supported platform installation method.

## Moving an existing Helm release

Helm stores release ownership in the release namespace. An existing Models Web
Application release in `kubeflow` cannot be upgraded into `kserve` by changing
`--namespace`. Install or upgrade the foundation chart, uninstall the old
release, remove the shared NetworkPolicy left by the previous platform
manifests, and install the release in `kserve`:

```sh
helm upgrade --install kubeflow-namespaces \
  ./common/kubeflow-namespace/helm \
  --namespace default

helm uninstall kserve-models-web-application --namespace kubeflow

kubectl delete -n kubeflow --ignore-not-found \
  networkpolicy.networking.k8s.io/kserve-models-web-application

helm install kserve-models-web-application \
  ./experimental/helm/charts/kserve-ui \
  --namespace kserve \
  --values ./experimental/helm/charts/kserve-ui/ci/kubeflow-values.yaml
```

This migration causes a short Models Web Application interruption. It does not
delete user `InferenceService` resources or model-serving workloads.

## Comparison

```bash
python3 tests/run_helm_kustomize_comparison.py kserve-models-web-application --all-scenarios
```

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../../tests/README.md).
