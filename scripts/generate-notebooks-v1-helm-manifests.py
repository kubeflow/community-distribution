#!/usr/bin/env python3
"""Generate the Kubeflow Notebooks Helm chart payloads.

Component-specific configuration only. The parsing, validation, custom resource
definition retention, deterministic rendering and atomic replacement live in
scripts/helm_manifest_generator.py so every component shares one engine.

The chart vendors every resource. No resource is rendered from a hand-written
template yet, so no Kustomize-declared value is exposed through values.yaml.
Exposing images and params.env entries is deliberately a later change.
"""

import argparse
import importlib.util
import sys

from pathlib import Path

ENGINE_PATH = Path(__file__).resolve().parent / "helm_manifest_generator.py"
_SPEC = importlib.util.spec_from_file_location("helm_manifest_generator", ENGINE_PATH)
engine = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(engine)


CONFIGURATION = engine.GeneratorConfiguration(
    component_name="Notebooks",
    kustomize_path=Path("applications/notebooks-v1/helm/kustomize"),
    output_path=Path("applications/notebooks-v1/helm/manifests"),
    generator_script="scripts/generate-notebooks-v1-helm-manifests.py",
    synchronize_script="scripts/synchronize-notebooks-v1-manifests.sh",
)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Generate payloads for the Kubeflow Notebooks Helm chart."
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Path to the kubeflow/community-distribution repository.",
    )
    return parser.parse_args()


def main():
    arguments = parse_arguments()
    try:
        resource_count, payload_filenames = engine.generate_manifests(
            arguments.repository_root, CONFIGURATION
        )
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        f"Generated {resource_count} Notebooks resources across "
        f"{len(payload_filenames)} files."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
