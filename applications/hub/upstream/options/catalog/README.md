# Model Catalog Manifests

This directory contains manifests for deploying the Model Catalog using Kustomize.

## Deployment

The model catalog manifests deploy a PostgreSQL database, set `POSTGRES_PASSWORD` in `postgres.env` before deploying the manifests. On Linux, you can generate a random password with:

```sh
(echo POSTGRES_USER=postgres ; echo -n POSTGRES_PASSWORD=; dd if=/dev/random of=/dev/stdout bs=15 count=1 status=none | base64) >base/postgres.env
```

To deploy the Model Catalog to your Kubernetes cluster (without Kubeflow--see below for Istio support), run the following command from this directory:

```sh
kubectl apply -k base -n <your-namespace>
```

Replace `<your-namespace>` with the Kubernetes namespace where you want to deploy the catalog.

This command will create:
*   A `Deployment` to run the Model Catalog server.
*   A `Service` to expose the Model Catalog server.
*   A `ConfigMap` named `model-catalog-sources` containing an empty configuration for catalog sources.
*   A `StatefulSet` with a PostgreSQL database
*   A `PersistentVolumeClaim` for PostgreSQL

The `base` catalog is empty, you may alternatively load the `demo` manifests to include generated test data:

```sh
kubectl apply -k overlays/demo -n <your-namespace>
```

For deployment in a Kubeflow environment with Istio support, also apply the `options/istio` directory:

```sh
kubectl apply -k options/istio -n <your-namespace>
```

## Configuring Catalog Sources

The Model Catalog is configured via the `sources.yaml` file. This file is **not** a Kubernetes manifest itself, but rather a configuration file for the application.

When you run `kubectl apply -k .`, Kustomize generates a `ConfigMap` that includes `sources.yaml` and any referenced local YAML catalog files. This `ConfigMap` is then mounted into the Model Catalog pod, making the files available to the application.

### Adding your own YAML-based catalog

You can define your own model catalog by providing a YAML file with model definitions. Here's how to add your own catalog source:

1.  **Create your catalog definition file.** Create a new YAML file with your model definitions. You can use `sample-catalog.yaml` as a reference for the format. Let's say you name it `my-catalog.yaml` and place it in this directory.

2.  **Add your file to the ConfigMap.** Edit `kustomization.yaml` to include your new file in the `configMapGenerator`:

    ```yaml
    # kustomization.yaml
    ...
    configMapGenerator:
    - behavior: create
      files:
      - sources.yaml=sources.yaml
      - sample-catalog.yaml=sample-catalog.yaml
      - my-catalog.yaml=my-catalog.yaml # <-- Add your file here
      name: sources
      options:
        disableNameSuffixHash: true
    ```

3.  **Add a new source entry.** Edit `sources.yaml` to add a new entry for your catalog under the `catalogs` list.

    ```yaml
    # sources.yaml
    catalogs:
    - name: Sample Catalog
      id: sample_custom_catalog
      type: yaml
      enabled: true
      properties:
        yamlCatalogPath: sample-catalog.yaml
    - name: My Custom Catalog
      id: my_custom_catalog
      type: yaml
      enabled: true
      properties:
        yamlCatalogPath: my-catalog.yaml # <-- Path to your file
    ```
    The `yamlCatalogPath` must be the filename of your catalog definition, as it will be mounted into the same directory as `sources.yaml` inside the pod.

4.  **Apply the changes.**

    ```sh
    kubectl apply -k . -n <your-namespace>
    ```

### Multiple Catalog Sources

The Model Catalog can be configured with multiple sources. You can add multiple entries to the `catalogs` list in `sources.yaml`. The catalog application only loads the single `sources.yaml` file specified at startup, so all sources must be defined within that file.



### Catalog Source Configuration Details

Each entry in the `catalogs` list configures a single catalog source.

#### Common Properties

-   **`name`** (*string*, required): A user-friendly name for the catalog source.
-   **`id`** (*string*, required): A unique identifier for the catalog source.
-   **`type`** (*string*, required): The type of catalog source. Currently supported types are: `yaml`.
-   **`enabled`** (*boolean*, optional): Whether the catalog source is enabled. Defaults to `true`.

#### `yaml` source type properties

The `yaml` type sources model metadata from a local YAML file.

-   **`yamlCatalogPath`** (*string*, required): The path to the YAML file containing the model definitions. This file must be available in the `ConfigMap` alongside `sources.yaml`.
-   **`excludedModels`** (*string list*, optional): A list of models to exclude from the catalog. These can be an exact name with a tag (e.g., `model-a:1.0`) or a pattern ending with `*` to exclude all tags for a model (e.g., `model-b:*`).

##### Example `sources.yaml` entry

```yaml
catalogs:
  - name: Sample Catalog
    id: sample_custom_catalog
    type: yaml
    enabled: true
    properties:
      yamlCatalogPath: sample-catalog.yaml
      excludedModels:
      - model-a:1.0
      - model-b:*
```

### Sample Catalog File

You can refer to `sample-catalog.yaml` in this directory for an example of how to structure your model definitions file.
