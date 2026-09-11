# KServe Helm Chart

This chart renders the current KServe Kustomize component,
`applications/kserve/kserve`, with Helm. Kustomize remains the source of truth.
The synchronization script builds the component once and writes deterministic
payloads under `manifests/`, which one small template loads with `.Files.Get`:
`platform-resources.yaml` for the control plane and one file per custom
resource definition under `custom-resource-definitions/`, because Helm refuses
any chart file above 5 MiB and the sixteen definitions together weigh 6.7 MB.

Helm does not send `.Files.Get` content through the template renderer, so the
Go template expressions that KServe ships in `inferenceservice-config` (the
path-based routing template `/serving/{{ .Namespace }}/{{ .Name }}`) and in
every `ClusterServingRuntime` are emitted literally instead of being resolved
to empty strings.

The payload carries every decision of the Kustomize component: the restricted
Pod Security Standard hardening of the storage initializer, the Istio sidecar
opt-out of the three controllers, the omission of the LocalModel node agent
and of the LLM inference service configuration templates with their validation
webhook, the path-based ingress configuration, the aggregated Kubeflow roles
and the webhook NetworkPolicy.

## Prerequisites

| chart | provides |
| --- | --- |
| `kubeflow-namespaces` (`common/kubeflow-namespace/helm`) | `Namespace/kserve` with its Pod Security labels |
| `cert-manager` (`common/cert-manager/helm`) | the webhook certificates |
| `istio` (`common/istio/helm`) and Knative Serving | the ingress and cluster-local gateways the inference service configuration refers to |

The chart requires its release namespace to be `kserve` and refuses to install
anywhere else. It does not create or own that namespace; the
`kubeflow-namespaces` foundation chart does. **Never pass
`--create-namespace`**: Helm 4 replaces the existing namespace with a bare one
and removes the `pod-security.kubernetes.io/enforce: restricted` label.

## Installation

Install in two release revisions. The payload contains cluster serving runtimes
and a cluster storage container, which cannot be created before their custom
resource definitions are established, and Helm does not wait for that on its
own.

```bash
helm install kserve ./applications/kserve/kserve/helm \
  --namespace kserve \
  --set resources.enabled=false \
  --wait

for name in $(helm get manifest kserve --namespace kserve |
    awk '$0 == "kind: CustomResourceDefinition" {c = 1; next} c && /^  name: / {print $2; c = 0}'); do
  kubectl wait --for=condition=Established "crd/${name}" --timeout=120s
done

helm upgrade kserve ./applications/kserve/kserve/helm \
  --namespace kserve \
  --wait --timeout 10m
```

`tests/kserve_helm_install.sh` is this procedure as continuous integration
runs it, followed by the readiness waits of the Kustomize installer.

The Models Web Application is a separate component, `applications/kserve/kserve-ui`.

## Configuration

| Value | Default | Purpose |
| --- | --- | --- |
| `scenario` | `platform` | Rendered Kustomize parity scenario. Only `platform` is supported. |
| `customResourceDefinitions.enabled` | `true` | Render the sixteen KServe custom resource definitions. |
| `resources.enabled` | `true` | Render the control plane. Set to `false` for the first release revision. |

Values that the Kustomize component declares through patches, such as the
ingress configuration and the controller images, are not exposed. Exposing one
means rendering the resource that carries it from a hand-written template,
which is a separate change.

## Custom resource definition lifecycle

The sixteen definitions are rendered from `templates/` and carry
`helm.sh/resource-policy: keep`. This deviates from Helm's documented
recommendation to place custom resource definitions in `crds/`, deliberately:
Helm never upgrades or deletes anything in `crds/`, which would freeze every
schema at its first installed version. Rendering them as templates keeps the
schemas upgradeable, while the retention policy stops `helm uninstall` from
deleting existing InferenceServices, runtimes and caches.

| operation | definitions | custom resources |
| --- | --- | --- |
| `helm install` | created | none yet |
| `helm upgrade` | updated to the synchronized upstream version | kept |
| `helm uninstall` | kept (`helm.sh/resource-policy: keep`) | kept |

Because they are templates rather than `crds/` content, Helm's `--skip-crds`
option has no effect on them. Use `customResourceDefinitions.enabled=false`
when an administrator or another release already owns them.

## How this chart is kept up to date

`COMMIT` in `scripts/synchronize-kserve-kserve-manifests.sh` is the single
upstream version. The script copies the upstream bundle, regenerates the
payloads from the component and sets `appVersion`:

```bash
python3 -m pip install pyyaml "ruamel.yaml==0.19.1"
KUBEFLOW_SYNCHRONIZE_NO_COMMIT=true \
  ./scripts/synchronize-kserve-kserve-manifests.sh
```

Do not edit files under `manifests/` directly. Review a generated payload change
by resource identity and upstream source boundary first, then regenerate and
confirm `git diff` is empty. The replay proves the generator is deterministic; it
cannot tell you whether a new upstream release introduced an unintended webhook,
permission or policy change.

## Kustomize Mapping

- `ci/values-platform.yaml`: `applications/kserve/kserve`, except
  `Namespace/kserve`, which the `kubeflow-namespaces` chart renders and
  compares.

## Comparison

```bash
helm lint applications/kserve/kserve/helm --namespace kserve
python3 tests/run_helm_kustomize_comparison.py kserve platform
python3 tests/kserve_helm_chart_test.py
python3 tests/kserve_helm_manifest_generator_test.py
```

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../../tests/README.md).
