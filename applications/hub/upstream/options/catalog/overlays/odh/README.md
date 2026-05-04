# ODH Overlay

These manifests deploy model catalog with the catalogs from Open Data Hub's [Model Metadata Collection](https://github.com/opendatahub-io/model-metadata-collection/), mirroring the default configuration from [Model Registry Operator](https://github.com/opendatahub-io/model-registry-operator/). This is intended to provide real-world data for development and as an example for providing catalog metadata that's bigger than will fit in a ConfigMap. The manifests aren't suitable for much else, because the models themselves are in private OCI repositories.

## Tilt

To use these manifests from Tilt, make a `local` directory as a sibling of this directory, which a `kustomization.yaml` that imports these manifests. From the repo root, this is:

```sh
mkdir -p manifests/kustomize/options/catalog/overlays/local
cat >manifests/kustomize/options/catalog/overlays/local/kustomization.yaml <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- ../odh
EOF
```

Then start Tilt as normal:

```sh
make -C devenv tilt-up
```

If you want to add more models for development, replace the `model-catalog-sources` ConfigMap in `kustomization.yaml`:

```yaml
configMapGenerator:
- behavior: replace
  files:
  - sources.yaml
  - catalog.yaml
  name: model-catalog-sources
  options:
    disableNameSuffixHash: true
```

Create `sources.yaml` and `catalog.yaml` [in the usual way](../../README.md).
