#!/usr/bin/env python3
"""Generate the KServe Helm chart payloads.

Component-specific configuration only. The parsing, validation, custom resource
definition retention, deterministic rendering and atomic replacement live in
scripts/helm_manifest_generator.py so every component shares one engine.
"""

import argparse
import importlib.util
import sys

from pathlib import Path

ENGINE_PATH = Path(__file__).resolve().parent / "helm_manifest_generator.py"
_SPEC = importlib.util.spec_from_file_location("helm_manifest_generator", ENGINE_PATH)
engine = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(engine)


# The component's own kustomization.yaml is the source: a chart-side wrapper
# kustomization under helm/ cannot reference its parent directory, because
# Kustomize rejects a root that contains an already visited root.
CONFIGURATION = engine.GeneratorConfiguration(
    component_name="KServe",
    kustomize_path=Path("applications/kserve/kserve"),
    output_path=Path("applications/kserve/kserve/helm/manifests"),
    generator_script="scripts/generate-kserve-helm-manifests.py",
    synchronize_script="scripts/synchronize-kserve-kserve-manifests.sh",
    # Together the sixteen definitions weigh 6.7 MB and Helm refuses any chart
    # file above 5 MiB, so each definition is written to its own file; the
    # largest single one is about 2.2 MB.
    crds_payload_directory="custom-resource-definitions",
    # The Kustomize component creates Namespace/kserve; on the Helm side the
    # kubeflow-namespaces foundation chart owns every platform namespace, and a
    # resource belongs to exactly one release, so the payload leaves it out.
    excluded_resources=(("Namespace", "kserve"),),
)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Generate payloads for the KServe Helm chart."
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
        f"Generated {resource_count} KServe resources across "
        f"{len(payload_filenames)} files."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
