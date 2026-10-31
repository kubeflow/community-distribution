# Cluster Local Gateway

This directory contains the Istio cluster-local-gateway configuration for Kubeflow.

## Architecture Overview

The cluster-local-gateway provides internal (cluster-local) routing for services, particularly for KServe inference services. It works alongside the main Istio ingress gateway to handle internal traffic.

## Important: knative-local-gateway Service

### The Naming Confusion
When investigating the gateway architecture, you will notice that:
- KServe and Knative reference a service called `knative-local-gateway`
- There are no pods with the label `app=knative-local-gateway`
- The `knative-local-gateway` service actually routes to `cluster-local-gateway` pods

### How It Works

1. **Service Definition**: The `knative-local-gateway` service is created by Knative Serving in the `istio-system` namespace
2. **Selector Override**: Kubeflow applies a kustomize patch that changes the service selector to point to `cluster-local-gateway` pods:
   ```yaml
   selector:
     app: cluster-local-gateway
     istio: cluster-local-gateway
   ```
3. **Actual Pods**: The traffic is handled by the `cluster-local-gateway` deployment defined in this directory

### Why This Design?

- **KServe Configuration**: KServe's ingress configuration explicitly references `knative-local-gateway` in its ConfigMap
- **Knative Integration**: Knative Serving creates the `knative-local-gateway` service by default
- **Resource Optimization**: Instead of running separate gateway pods, Kubeflow redirects the service to use existing `cluster-local-gateway` pods
- **Abstraction Layer**: This allows KServe to use its expected service name while leveraging Kubeflow's gateway infrastructure

### Verification

You can verify this architecture with:
```bash
# Check the service selector
kubectl get svc knative-local-gateway -n istio-system -o jsonpath='{.spec.selector}'
# Output: {"app":"cluster-local-gateway","istio":"cluster-local-gateway"}

# Verify no knative-local-gateway pods exist
kubectl get pods -n istio-system -l app=knative-local-gateway
# Output: No resources found

# See the actual pods handling the traffic
kubectl get pods -n istio-system -l app=cluster-local-gateway
```

## Configuration Files

- `cluster-local-gateway.yaml` - Main gateway deployment and service
- `gateway.yaml` - Istio Gateway resource configuration
- `gateway-authorizationpolicy.yaml` - Default authorization policy
- `kustomization.yaml` - Kustomize configuration

## Related Components

- KServe uses this gateway for inference service routing
- Knative Serving creates the `knative-local-gateway` service that routes here
- The patch is applied in `common/knative/knative-serving/overlays/gateways/`
