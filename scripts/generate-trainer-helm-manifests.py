#!/usr/bin/env python3
"""Generate three disjoint Trainer releases through the shared payload engine.

The API dependency is internal packaging, not a fourth installed release.
Each chart is replaced atomically; --check never writes any of the charts.
"""

import argparse
import importlib.util
import sys
from pathlib import Path

ENGINE_PATH = Path(__file__).resolve().parent / "helm_manifest_generator.py"
SPEC = importlib.util.spec_from_file_location("helm_manifest_generator", ENGINE_PATH)
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)

DEFINITIONS = ("apiextensions.k8s.io", "CustomResourceDefinition")
RUNTIMES = ("trainer.kubeflow.org", "ClusterTrainingRuntime")
COMMON = dict(
    kustomize_path=Path("applications/trainer/overlays"),
    generator_script="scripts/generate-trainer-helm-manifests.py",
    synchronize_script="scripts/synchronize-trainer-manifests.sh",
)
CONFIGURATIONS = (
    engine.GeneratorConfiguration(
        **COMMON,
        component_name="Trainer APIs",
        output_path=Path(
            "applications/trainer/helm-crds/charts/trainer-api-payload/manifests"
        ),
        included_resource_kinds=(DEFINITIONS,),
        crds_payload_directory="definitions",
        resources_payload_filename=None,
    ),
    engine.GeneratorConfiguration(
        **COMMON,
        component_name="Trainer control plane",
        output_path=Path("applications/trainer/helm/manifests"),
        excluded_resource_kinds=(DEFINITIONS, RUNTIMES),
        crds_payload_filename=None,
    ),
    engine.GeneratorConfiguration(
        **COMMON,
        component_name="Trainer runtimes",
        output_path=Path("applications/trainer/helm-runtimes/manifests"),
        included_resource_kinds=(RUNTIMES,),
        crds_payload_filename=None,
    ),
)


def main(argv=None):
    description = "Generate the three Trainer chart payloads."
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args(argv)
    engine_arguments = ["--check"] if arguments.check else []
    if arguments.repository_root is not None:
        engine_arguments.extend(["--repository-root", str(arguments.repository_root)])

    exit_status = 0
    for configuration in CONFIGURATIONS:
        status = engine.command_line(
            configuration,
            description,
            Path(__file__).resolve().parents[1],
            argv=engine_arguments,
        )
        if status:
            if not arguments.check:
                return status
            exit_status = status
    return exit_status


if __name__ == "__main__":
    sys.exit(main())
