# Install Kubeflow Model Registry

This folder contains [Kubeflow Model Registry](https://www.kubeflow.org/docs/components/model-registry/installation/) Kustomize manifests

## Overview

This is the full installation guide, for a quick install in an existing Kubeflow installation, follow [these instructions](https://www.kubeflow.org/docs/components/model-registry/installation/).
**Ensure you are running all these commands from the directory containing this README.md file (e.g.: you could check with `pwd`).**

## Kubeflow Central Dashboard Installation

These instructions assume that you've installed Kubeflow from the [manifests](https://github.com/kubeflow/manifests/), if you're using a distribution consult its documentation instead.

Kubeflow Central Dashboard uses [profiles](https://www.kubeflow.org/docs/components/central-dash/profiles/) to handle user namespaces and permissions. You will need to deploy Model Registry into a profile namespace.

> **🛈 Note:** If you're not sure of the profile name, you can find it in the name space drop-down on the Kubeflow Dashboard.

The commands in this section assume that you've defined an environment variable with the target profile namespace:

```sh
PROFILE_NAME=<your-profile>
```

Deploy Model Registry:

```sh
kubectl apply -k overlays/db -n $PROFILE_NAME
kubectl apply -k options/istio -n $PROFILE_NAME
```

Check that everything is up and running:

```bash
kubectl wait --for=condition=available-n $PROFILE_NAME deployment/model-registry-deployment --timeout=2m
kubectl logs -n $PROFILE_NAME deployment/model-registry-deployment
```

### CSI multi-profile setup

If you want to use the CSI storage initializer with Model Registry in profile namespaces, you only need to deploy the standard `ClusterStorageContainer` once globally. Workloads in specific namespaces can then append the `?namespace=<namespace>` query parameter to their `storageUri` to force the CSI initializer to route the request to the correct Model Registry in that namespace.

See [cmd/csi/GET_STARTED.md](../../cmd/csi/GET_STARTED.md) for the full multi-profile CSI workflow and examples.

Now, to install the Model Registry UI as a Kubeflow component, you need first to deploy the Model Registry UI:

```bash
kubectl apply -k options/ui/overlays/istio
```

And then to make it accessible through Kubeflow Central Dashboard, you need to edit the `centraldashboard-config` ConfigMap to add the Model Registry UI link to the Central Dashboard by running the following command:

```bash
kubectl get configmap centraldashboard-config -n kubeflow -o json | jq '.data.links |= (fromjson | .menuLinks += [{"icon": "assignment", "link": "/model-registry/", "text": "Model Registry", "type": "item"}] | tojson)' | kubectl apply -f - -n kubeflow
```

Alternatively, you can edit the ConfigMap manually by running:

```bash
kubectl edit configmap -n kubeflow centraldashboard-config
```

```yaml
apiVersion: v1
data:
  links: |-
    {
        "menuLinks": [
            {
                "icon": "assignment",
                "link": "/model-registry/",
                "text": "Model Registry",
                "type": "item"
            },
            ...
```

Now you should be able to see the Model Registry UI in the Kubeflow Central Dashboard, and access to the Model Registry deployment in the profile namespace.

### Uninstall

To uninstall the Kubeflow Model Registry run:

```bash
# Uninstall Model Registry Instance
PROFILE_NAME=<your-profile>
kubectl delete -k overlays/db -n $PROFILE_NAME
kubectl delete -k options/istio -n $PROFILE_NAME

# Uninstall Model Registry UI
kubectl delete -k options/ui/overlays/istio
```

## Model Registry as a separate component Installation

The following instructions will summarize how to deploy Model Registry as separate component in the context of a default Kubeflow >=1.9 installation.

```bash
kubectl apply -k overlays/db -n kubeflow
```

As the default Kubeflow installation provides an Istio mesh, apply the necessary manifests:

```bash
kubectl apply -k options/istio -n kubeflow
```

Check everything is up and running:

```bash
kubectl wait --for=condition=available -n kubeflow deployment/model-registry-deployment --timeout=2m
kubectl logs -n kubeflow deployment/model-registry-deployment
```

Optionally, you can also port-forward the REST API container port of Model Registry to interact with it from your terminal:

```bash
kubectl port-forward svc/model-registry-service -n kubeflow 8081:8080
```

And then, from another terminal:

```bash
curl -sX 'GET' \
  'http://localhost:8081/api/model_registry/v1alpha3/registered_models?pageSize=100&orderBy=ID&sortOrder=DESC' \
  -H 'accept: application/json' | jq
```

### Usage

For a basic usage of the Kubeflow Model Registry, follow the [Kubeflow Model Registry getting started documentation](https://www.kubeflow.org/docs/components/model-registry/getting-started/)

### Uninstall

To uninstall the Kubeflow Model Registry run:

```bash
# Delete istio options
kubectl delete -k options/istio -n kubeflow

# Delete model registry db and deployment
kubectl delete -k overlays/db -n kubeflow
```

## Error `error: error connecting to datastore: Dirty database version {version}. Fix and force version.`

If you see this error for your model registry deployment, it means that your schema migration has failed. 

The solution to this problem requires the user to manually resolve the issue and change the database dirty state to '0' before traffic can be routed to the pod. 

You can accomplish this by using `kubectl exec` for the particular model registry db deployment and running the following query:

`USE metadb; UPDATE schema_migrations SET dirty = 0;`
