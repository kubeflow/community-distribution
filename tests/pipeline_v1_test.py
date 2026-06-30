#!/usr/bin/env python3

import kfp
import sys
import time
from kubernetes.client.models import V1Capabilities, V1SeccompProfile, V1SecurityContext
from kfp.components import func_to_container_op


def hello_world():
    print("Hello World from Kubeflow Pipelines V1!")
    return "Hello World"


def hello_world_pipeline():
    hello_world_task = func_to_container_op(hello_world, base_image="python:3.12")()
    hello_world_task.container.set_security_context(
        V1SecurityContext(
            allow_privilege_escalation=False,
            capabilities=V1Capabilities(drop=["ALL"]),
            privileged=False,
            read_only_root_filesystem=False,
            seccomp_profile=V1SeccompProfile(type="RuntimeDefault"),
            run_as_user=1000,
            run_as_group=0,
            run_as_non_root=True,
        )
    )


def run_v1_pipeline(token, namespace):
    client = kfp.Client(host="http://localhost:8080/pipeline", existing_token=token)

    experiment = client.create_experiment("v1-pipeline-test", namespace=namespace)

    pipeline_run = client.create_run_from_pipeline_func(
        hello_world_pipeline,
        experiment_name=experiment.name,
        run_name="v1-hello-world",
        namespace=namespace,
        arguments={},
    )

    for iteration in range(15):
        pipeline_status = client.get_run(pipeline_run.run_id).run.status

        if pipeline_status == "Succeeded":
            return
        elif pipeline_status not in ["Running", "Pending"]:
            sys.exit(1)

        time.sleep(10)

    sys.exit(1)


if __name__ == "__main__":
    from kfp import compiler

    compiler.Compiler().compile(
        pipeline_func=hello_world_pipeline,
        package_path="pipeline_v1.yaml",
    )
    if len(sys.argv) != 3:
        sys.exit(1)

    run_v1_pipeline(sys.argv[1], sys.argv[2])
