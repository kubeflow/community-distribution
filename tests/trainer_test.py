#!/usr/bin/env python3

"""Trainer integration test using the Kubeflow SDK.

Follows the same pattern as pipeline_v2_test.py: use the SDK client
to create a training job, then poll until completion.
"""

import json
import sys

from kubernetes import client as kubernetes_client
from kubernetes import config as kubernetes_config

from kubeflow.common.types import KubernetesBackendConfig
from kubeflow.trainer import CustomTrainer, TrainerClient


def training_function():
    """Minimal training function with synthetic data.

    Uses a simple feedforward network on random tensors to verify
    that the Trainer SDK can create and run a TrainJob end-to-end.
    """
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, TensorDataset

    model = nn.Sequential(nn.Linear(784, 256), nn.ReLU(), nn.Linear(256, 10))
    optimizer = torch.optim.SGD(model.parameters(), lr=0.01)

    training_dataset = TensorDataset(torch.randn(64, 784), torch.randint(0, 10, (64,)))
    for inputs, targets in DataLoader(training_dataset, batch_size=32):
        loss = torch.nn.functional.cross_entropy(model(inputs), targets)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
        print(f"loss={loss.item():.4f}")

    print("Training complete")


def print_diagnostic_information(job_name, namespace):
    """Print diagnostic information for debugging timeout failures."""
    custom_objects_api = kubernetes_client.CustomObjectsApi()
    core_api = kubernetes_client.CoreV1Api()

    print("=== TrainJob status ===")
    try:
        trainjob = custom_objects_api.get_namespaced_custom_object(
            group="trainer.kubeflow.org",
            version="v1alpha1",
            namespace=namespace,
            plural="trainjobs",
            name=job_name,
        )
        print(json.dumps(trainjob, indent=2, default=str))
    except Exception as error:
        print(f"Failed to get TrainJob: {error}")

    print("=== Pods ===")
    try:
        pod_list = core_api.list_namespaced_pod(
            namespace=namespace,
            label_selector=f"jobset.sigs.k8s.io/jobset-name={job_name}",
        )
        for pod in pod_list.items:
            print(f"Pod: {pod.metadata.name}  Phase: {pod.status.phase}")
            try:
                pod_logs = core_api.read_namespaced_pod_log(
                    name=pod.metadata.name,
                    namespace=namespace,
                    tail_lines=50,
                )
                print(pod_logs)
            except Exception as log_error:
                print(f"Failed to get logs for {pod.metadata.name}: {log_error}")
    except Exception as error:
        print(f"Failed to list pods: {error}")

    print("=== Events ===")
    try:
        event_list = core_api.list_namespaced_event(namespace=namespace)
        sorted_events = sorted(
            event_list.items,
            key=lambda event: event.metadata.creation_timestamp or "",
        )
        for event in sorted_events[-20:]:
            print(
                f"{event.metadata.creation_timestamp}  "
                f"{event.reason}: {event.message}"
            )
    except Exception as error:
        print(f"Failed to list events: {error}")

    sys.stdout.flush()


if __name__ == "__main__":
    namespace = sys.argv[1] if len(sys.argv) > 1 else "kubeflow-user-example-com"

    kubernetes_config.load_kube_config()

    trainer_client = TrainerClient(
        backend_config=KubernetesBackendConfig(namespace=namespace)
    )

    job_name = trainer_client.train(
        trainer=CustomTrainer(
            func=training_function,
            num_nodes=1,
            resources_per_node={"memory": "2Gi", "cpu": "1"},
            packages_to_install=["torch<3"],
            pip_index_urls=["https://download.pytorch.org/whl/cpu"],
        ),
    )
    print(f"Created TrainJob: {job_name}")

    try:
        trainer_client.wait_for_job_status(job_name, timeout=300, polling_interval=5)
        print("TrainJob completed successfully")
    except RuntimeError:
        print(f"\n=== ERROR: TrainJob {job_name} failed ===")
        print_diagnostic_information(job_name, namespace)
        sys.stdout.flush()
        raise
    except TimeoutError:
        print(f"\n=== TIMEOUT: TrainJob {job_name} did not complete in 300s ===")
        print_diagnostic_information(job_name, namespace)
        sys.stdout.flush()
        raise
