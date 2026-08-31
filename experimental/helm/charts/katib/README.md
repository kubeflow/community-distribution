# Katib Helm Chart

A Helm chart for deploying [Katib](https://github.com/kubeflow/katib) - AutoML on Kubernetes.

## Description

Katib is a Kubernetes-native project for automated machine learning (AutoML). Katib supports hyperparameter tuning, early stopping, and neural architecture search (NAS).

## Comparison

```bash
python3 tests/run_helm_kustomize_comparison.py katib --all-scenarios
```

How this chart is compared, including every declared allowance, is in
[`ci/comparison.yaml`](ci/comparison.yaml); the descriptor format is documented in
[`tests/README.md`](../../../../tests/README.md).
