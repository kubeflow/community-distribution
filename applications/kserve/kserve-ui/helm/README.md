# Models UI for the Kubeflow platform

This chart installs the nine resources rendered by
`kustomize build applications/kserve/kserve-ui`, using the distribution's
models-web-application v1.0.5 configuration. It runs independently of the KServe
controller release. The shared generator writes literal YAML under `manifests/`;
Helm reads it with `.Files.Get`, without evaluating embedded template expressions.

## Installation

Use Helm 4. Install the `kubeflow-namespaces` foundation chart, Istio and its
Kubeflow gateway, Dex/OAuth2 Proxy, Profile authorization and the KServe controller
first. The existing `kserve` Namespace belongs to the foundation release; this
chart neither creates nor deletes it. Istio must provide the VirtualService and
AuthorizationPolicy APIs. A Profile and inference service are needed to exercise
the UI; installing this chart does not create either.

From the repository root:

```bash
helm lint applications/kserve/kserve-ui/helm --namespace kserve
helm install kserve-models-web-application applications/kserve/kserve-ui/helm \
  --namespace kserve --wait --timeout 5m
```

The integration installer uses `helm upgrade --install --reset-values`, so a
KServe controller reinstall can safely revisit the independent UI release with
the chart's fixed platform defaults. The Helm integration installer delegates UI installation from
`tests/kserve_helm_install.sh` to `tests/kserve_ui_helm_install.sh`. The Kustomize
installer remains available for the Kustomize integration workflow. Never run
both installation paths against the same objects.

The only scenario is `platform`. The chart fixes names, namespace, image,
identity headers, application prefix and routes to the distribution baseline.
Unknown values fail schema validation; unsupported legacy values are not silently
ignored. The baseline uses the fixed ConfigMap name
`kserve-models-web-application-config`, which this chart preserves. A change to
that ConfigMap alone does not change the Deployment's Pod template or restart
its Pods. After upgrading a configuration consumed through environment variables,
restart the Deployment so new Pods receive the updated values:

```bash
kubectl rollout restart deployment/kserve-models-web-application --namespace kserve
kubectl rollout status deployment/kserve-models-web-application --namespace kserve
```

## Existing installations and values

The experimental chart at `experimental/helm/charts/kserve-ui` remains available
with its existing interface and comparison scenario. This chart does not remove
or silently adopt an experimental or Kustomize installation. The two charts
render overlapping resource names and must not be installed concurrently. There
is no validated in-place migration procedure in this draft; existing operators
should retain their current installation until selector, values and ownership
compatibility have been tested for their configuration. Routine `--take-ownership`
and `--force-conflicts` are not installation instructions.

| Existing experimental configuration | Initial platform chart decision |
| --- | --- |
| Image registry/tag, replicas, scheduling, resources, probes, volumes and container security | Use distribution defaults; keep the experimental chart for existing customizations. |
| Identity headers, UI prefix and Grafana configuration | Keep source settings together with their route and security references. |
| Namespace and resource name overrides | Fixed `kserve` namespace and source identities. |
| Service ports/type, RBAC toggles/rules, arbitrary labels/annotations | Keep the source topology and permissions. |
| Istio routes, authorization and NetworkPolicy overrides | Preserve the authenticated distribution boundary. |

This deliberately small interface follows the merged Notebooks chart. A future
value must describe a supported installation need, preserve the default baseline
and carry a focused behavior test. No general patch or templating interface is
introduced.

## Upgrade, rollback and removal

```bash
helm upgrade kserve-models-web-application applications/kserve/kserve-ui/helm \
  --namespace kserve --wait --timeout 5m
helm history kserve-models-web-application --namespace kserve
# Replace the revision with a compatible, previously deployed full chart.
helm rollback kserve-models-web-application 1 --namespace kserve --wait --timeout 5m
helm uninstall kserve-models-web-application --namespace kserve --wait --timeout 5m
```

Uninstall removes the UI Deployment, configuration, route, Service, service
account, UI-specific RBAC and policies. It does not own the Namespace, KServe
controllers, inference definitions or users' InferenceServices. The UI is
unavailable while it is uninstalled. Reinstallation restores the route and UI;
this draft makes no uninterrupted-service claim during upgrades or rollback.

The Helm integration workflow retains the existing authenticated UI object lookup
and unauthorized-account rejection checks in `tests/kserve_test.sh`. With
`KSERVE_UI_MANAGED_BY_HELM=true`, that test also calls
`tests/kserve_ui_helm_lifecycle_test.sh` while a real Ready InferenceService exists.
The lifecycle test checks unchanged upgrade, a disposable changed chart with two
UI replicas, rollback, uninstall and reinstall. It asserts that the Namespace,
KServe controller Deployment and user InferenceService retain their UIDs, and
checks readiness. The caller then repeats the authenticated API lookup and the
unauthorized-account check after recovery. These cluster gates are implemented
but have not been executed locally for this draft.

## Synchronization and local checks

```bash
KUBEFLOW_SYNCHRONIZE_NO_COMMIT=true ./scripts/synchronize-kserve-ui-manifests.sh
python3 scripts/generate-kserve-ui-helm-manifests.py --check
python3 tests/kserve_ui_helm_chart_test.py -v
python3 tests/run_helm_kustomize_comparison.py \
  kserve-models-web-application-platform --all-scenarios
python3 tests/helm_release_size.py kserve-models-web-application-platform
```

Synchronization imports upstream manifests, updates both chart application
versions and the legacy image value, regenerates this chart and lints both
charts. It stages only the files it actually writes. Local overlay, generator or
shared-engine edits also trigger synchronization replay; freshness checks catch
unregenerated payloads on every comparison run. Review generated payloads by
regenerating and confirming an empty `git diff`; do not hand-edit them.

The direct component baseline has no aggregated ClusterRole. This draft is
stacked on the KServe Helm installer change, its aggregated-role prerequisite
and the explicit no-definitions generator extension;
that dependency is about integration ownership, not a UI-specific empty-rule
transformation.
