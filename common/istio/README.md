# Istio

We use Istio with CNI as the default configuration as described here <https://istio.io/latest/docs/setup/additional-setup/cni/>.

CNI eliminates privileged init containers and improves security compliance with Pod Security Standards. This configuration also enables native sidecars for Istio through the `ENABLE_NATIVE_SIDECARS=true` environment variable in istiod.

## Installation Options

### Default (CNI-enabled - Recommended)
```bash
kubectl apply -k istio-install/overlays/oauth2-proxy
```

### GKE-specific CNI
GKE mounts `/opt/cni/bin` as read-only for security reasons, preventing the Istio CNI installer from writing the CNI binary. Use the GKE-specific overlay: `kubectl apply -k common/istio/istio-install/overlays/gke`. This overlay uses GKE's writable CNI directory at `/home/kubernetes/bin`. For more details, see [Istio CNI Prerequisites](https://istio.io/latest/docs/setup/additional-setup/cni/#prerequisites) and [Platform Prerequisites](https://istio.io/latest/docs/ambient/install/platform-prerequisites/)

#### For Google Kubernetes Engine clusters:
```bash
kubectl apply -k istio-install/overlays/gke
```

### Ambient Mode (Sidecar-free Service Mesh)
Istio Ambient Mode eliminates sidecars, reducing resource overhead while maintaining full L4/L7 traffic processing capabilities.

```bash
# OAuth2-Proxy
kubectl apply -k istio-install/overlays/ambient-oauth2-proxy

# OAuth2-Proxy on Google Kubernetes Engine (GKE)
kubectl apply -k istio-install/overlays/ambient-oauth2-proxy-gke
```

**Important:** Ambient mode requires PSS Privileged (not Baseline or Restricted) for the `istio-system` namespace. The ztunnel component needs `CAP_SYS_ADMIN`, `CAP_NET_ADMIN`, and `CAP_NET_RAW` capabilities for transparent proxying and network namespace operations. The `istio-system` namespace is automatically configured with PSS privileged label when using ambient mode components.

**Note:** Ambient mode uses Kustomize components (`components/ambient-mode/`) for composable configuration without duplication.

### Insecure Istio (CNI-disabled)
For environments that don't support CNI:
```bash
kubectl apply -k istio-install/overlays/insecure
```

## CNI Benefits

- **Security**: No privileged init containers required
- **Compatibility**: Better alignment with Pod Security Standards
- **Performance**: Native sidecars support for improved lifecycle management
- **Simplicity**: Reduces container complexity
- **Startup Time**: Significantly faster startup in many cases

## Istio Sidecar Egress

We limit egress route creation in istio sidecars to reduce the memory overhead in every sidecar as described in this [pull request](https://github.com/kubeflow/community-distribution/pull/3206).

This may cause issues for users extending or modifying the kubeflow deployment since it can cause egress traffic not listed in the hosts section of the [default sidecar implementation](./istio-install/base/sidecar-prune-egress.yaml) to not use MTLS.

This can cause the following kinds of errors:
1. Error ```RBAC: Access Denied``` returned from the destination
2. Error ```rbac_access_denied_matched_policy[none]``` in the destination sidecar if [authorizationpolicies](https://istio.io/latest/docs/reference/config/security/authorization-policy/#Source-principals) use MTLS required rules
3. Error ```upstream connect error or disconnect/reset before headers``` if MTLS is set to strict for the destination sidecar

You may add additional [sidecar configurations](https://istio.io/latest/docs/reference/config/networking/sidecar) to override the default configuration for affected traffic.

## Troubleshooting

If you still encounter probelms, even with native sidecars enabled, you might try the following:

1. Use `runAsUser: 1337` in your init containers, or
2. Add the annotation `traffic.sidecar.istio.io/excludeOutboundIPRanges: 0.0.0.0/0` to your KServe inferenceservices

### VirtualService Conflicts with KServe Path-Based Routing

When deploying KServe with path-based routing alongside KubeFlow, you may encounter 404 errors due to Istio VirtualService conflicts. This is an upstream Istio routing behavior issue (see [istio/istio#57404](https://github.com/istio/istio/issues/57404)).

**Problem:** KubeFlow uses wildcard VirtualServices (`hosts: ['*']`) while KServe creates specific-host VirtualServices (`hosts: ['your-domain.com']`), causing Istio's routing logic to fail when matching requests to the specific host.

**Symptoms:**
- KServe InferenceServices return 404 errors when accessed via their specific domain
- KubeFlow Central Dashboard and other services work normally
- KServe services work when accessed via different paths but not the root path

**Workaround:** Align the hosts of VirtualServices created by KServe with the KubeFlow VirtualServices:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: set-hosts-new-vs
  annotations:
    policies.kyverno.io/title: Override hosts of new Istio VirtualServices to align with other KubeFlow VirtualServices
spec:
  rules:
  - name: override-vs-hosts
    preconditions:
      all:
        - key: "{{ request.object.spec.hosts || [] }}"
          operator: NotEquals
          value: ["*"]
        # The problem happens only with VirtualServices for the `kubeflow-gateway` gateway
        - key: "{{ request.object.spec.gateways || []}}"
          operator: AnyIn
          value:
          - kubeflow/kubeflow-gateway
          - kubeflow-gateway
        # Make sure to ignore VirtualService with `mesh` gateway
        # Otherwise this will lead to connectivity problems between the KubeFlow dashboard and profile controller
        - key: "{{ request.object.spec.gateways || []}}"
          operator: AllNotIn
          value:
          - mesh
    match:
      any:
      - resources:
          kinds:
          - networking.istio.io/v1/VirtualService
          namespaceSelector:
            matchLabels:
              app.kubernetes.io/part-of: kubeflow-profile
    mutate:
      patchStrategicMerge:
        spec:
          hosts:
          - "*"
```

**Steps to apply the fix:**
1. Create the Kyverno policy

**References:**
- Upstream Istio issue: https://github.com/istio/istio/issues/57404
- Upstream KServe issue to make the host configurable: https://github.com/kserve/kserve/issues/4750
- KServe path-based routing documentation: https://kserve.github.io/website/docs/admin-guide/configurations#path-template
- Path-based routing test in CI: [.github/workflows/kserve_test.yaml](../../.github/workflows/kserve_test.yaml) (see `test-basic-kserve` job)
- VirtualService path-based routing implementation: [tests/kserve_test.sh](../../tests/kserve_test.sh#L16-L42)

## Upgrade Istio Manifests
For upgrading Istio to newer versions, use the synchronization script:

```bash
scripts/synchronize-istio-manifests.sh
```

## Changes to Istio's upstream manifests
### Profile modifications

- Add `cluster-local-gateway` component for KServe
- Disable EgressGateway component
- Enable CNI by default

### Kustomize modifications

- Remove PodDisruptionBudgets for compatibility
- Add AuthorizationPolicies for security
- Add Gateway CRs and namespace objects
- Configure TCP KeepAlives
- Disable tracing to prevent DNS issues
- Set `ENABLE_DEBUG_ON_HTTP=false` for security
- Add seccomp profiles for Pod Security Standards compliance
