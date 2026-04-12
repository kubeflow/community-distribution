## Overview
An opt-in kustomize component providing a complete monitoring foundation for Kubeflow clusters. The base component focuses on GPU workloads (NVIDIA DCGM + AMD ROCm) and installs Prometheus Operator, Grafana Operator, GPU ServiceMonitors, and three Grafana dashboards. Energy metrics via **Kepler** are available as a separate, optional sub-component and are not part of the default installation.

> **Note:** All ServiceMonitor resources are created in the `kubeflow-monitoring-system` namespace (forced by the base kustomization). The `spec.namespaceSelector` field on each ServiceMonitor controls which target namespaces are scraped. If the target namespace (e.g. `gpu-operator`) does not exist, Prometheus will simply find no matching endpoints — no error is raised.

## Prerequisites
| Prerequisite | Required for | Notes |
|---|---|---|
| Kubernetes 1.27+ | Everything | |
| kustomize v5+ | Installation | |
| NVIDIA GPU Operator | NVIDIA ServiceMonitor | Runs in `gpu-operator` ns — ServiceMonitor scrapes it via `spec.namespaceSelector`; silent if absent |
| AMD GPU Operator | AMD ServiceMonitor | Runs in `kube-amd-gpu` ns — ServiceMonitor scrapes it via `spec.namespaceSelector`; silent if absent |
| kube-state-metrics | GPU Namespace Usage + Availability dashboards | **Without it 2/3 dashboards render blank with no error** — install via kube-prometheus-stack or standalone |

### Architecture Support
| Component | x86_64 | ARM64 |
|---|:---:|:---:|
| Core Stack (Prometheus, Grafana) | ✅ | ✅ |
| NVIDIA DCGM Exporter | ✅ | ⚠️ (Requires specific image) |
| AMD GPU Exporter | ✅ | ❌ |
| Kepler | ✅ | ✅ |

## Installation
```sh
# Main stack (Prometheus + Grafana + GPU ServiceMonitors + dashboards)
kustomize build common/observability/overlays/kubeflow | kubectl apply --server-side -f -

# Or via script
./tests/observability_install.sh

# Kepler energy metrics (OPTIONAL — separate step)
# Note: Kepler requires privileged access. See section below.
kustomize build common/observability/components/kepler | kubectl apply --server-side -f -
```
> `--server-side` is required — CRD bundles exceed client-side annotation size limits.

## What gets installed
| Resource | Namespace | Purpose |
|---|---|---|
| Prometheus Operator | kubeflow-monitoring-system | Manages Prometheus CR |
| Prometheus CR | kubeflow-monitoring-system | Scrapes all ServiceMonitors across all namespaces |
| Grafana Operator | kubeflow-monitoring-system | Manages Grafana, GrafanaDatasource, GrafanaDashboard CRs |
| Grafana CR | kubeflow-monitoring-system | Grafana instance |
| GrafanaDatasource | kubeflow-monitoring-system | Prometheus datasource, uid: prometheus |
| NVIDIA DCGM ServiceMonitor | kubeflow-monitoring-system | Scrapes DCGM exporter in `gpu-operator` ns via `spec.namespaceSelector` |
| AMD ROCm ServiceMonitor | kubeflow-monitoring-system | Scrapes device-metrics-exporter in `kube-amd-gpu` ns via `spec.namespaceSelector` |
| 3x GrafanaDashboard CRs | kubeflow-monitoring-system | GPU dashboards |
| Kepler DaemonSet (opt-in) | kepler | Per-pod energy/power draw metrics |
| Kepler ServiceMonitor (opt-in) | kubeflow-monitoring-system | Scrapes Kepler in the `kepler` ns via `spec.namespaceSelector` |

## Dashboards
| Dashboard | What it shows | Dependencies |
|---|---|---|
| GPU Cluster Usage | Cluster-wide GPU utilization, memory, count per node | DCGM or ROCm metrics |
| GPU Namespace Usage | Per-namespace GPU allocation and utilization | kube-state-metrics + DCGM |
| GPU Availability & Allocation | Allocation ratios, pending GPU sessions | kube-state-metrics |

## Accessing Grafana
```sh
kubectl port-forward svc/grafana-service -n kubeflow-monitoring-system 3000:3000
```
Open http://localhost:3000 — default credentials are `admin` / `admin` (managed via `grafana-admin-credentials` Secret).

> **Security warning:** These default credentials are provided for ease of initial access and must be rotated immediately for production use by updating the `grafana-admin-credentials` Secret or via the Grafana UI.

## Kepler (opt-in)
Kepler deploys to its own `kepler` namespace (PSS: privileged) to avoid impacting the PSS restricted posture of `kubeflow-monitoring-system`. It requires `privileged: true` to access `/proc`, `/sys`, and the container runtime socket for energy metrics.

## Reference
- CERN architecture: https://architecture.cncf.io/architectures/cern-scientific-computing/
- Issue: https://github.com/kubeflow/manifests/issues/3426
