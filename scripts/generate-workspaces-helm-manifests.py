#!/usr/bin/env python3
"""Generate the Kubeflow Workspaces Helm chart payloads.

Component-specific configuration only. The parsing, validation, custom resource
definition retention, deterministic rendering and atomic replacement live in
scripts/helm_manifest_generator.py so every component shares one engine.

The chart vendors every resource. No resource is rendered from a hand-written
template yet, so no Kustomize-declared value is exposed through values.yaml.
Exposing images and params.env entries is deliberately a later change.
"""

import importlib.util
import sys

from pathlib import Path

ENGINE_PATH = Path(__file__).resolve().parent / "helm_manifest_generator.py"
_SPEC = importlib.util.spec_from_file_location("helm_manifest_generator", ENGINE_PATH)
engine = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(engine)


CONFIGURATION = engine.GeneratorConfiguration(
    component_name="Workspaces",
    kustomize_path=Path("applications/workspaces/helm/kustomize"),
    output_path=Path("applications/workspaces/helm/manifests"),
    generator_script="scripts/generate-workspaces-helm-manifests.py",
    synchronize_script="scripts/synchronize-kubeflow-workspaces-manifests.sh",
)


def main():
    return engine.command_line(
        CONFIGURATION,
        description="Generate payloads for the Kubeflow Workspaces Helm chart.",
        default_repository_root=Path(__file__).resolve().parents[1],
    )


if __name__ == "__main__":
    sys.exit(main())
