# Kubeflow Hub Helm Chart

A Helm chart for deploying the Kubeflow Hub / Model Registry.

## Description

The Kubeflow Hub provides a centralized repository for managing machine learning model metadata, versions, and lineage. 

## Comparison

```bash
python3 tests/run_helm_kustomize_comparison.py hub --all-scenarios
```

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../../tests/README.md).
