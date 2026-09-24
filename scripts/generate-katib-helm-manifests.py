#!/usr/bin/env python3
"""Generate the Katib Helm chart payloads.

Component-specific configuration only. The parsing, validation, custom resource
definition retention, deterministic rendering and atomic replacement live in
scripts/helm_manifest_generator.py so every component shares one engine.

The payload is the installation that the distribution deploys,
applications/katib/upstream/installs/katib-with-kubeflow. Pinned Katib ships no
Helm chart to wrap, so the chart vendors every resource. No resource is rendered
from a hand-written template, so no Kustomize-declared value is exposed through
values.yaml.
"""

import importlib.util
import sys

from pathlib import Path

ENGINE_PATH = Path(__file__).resolve().parent / "helm_manifest_generator.py"
_SPEC = importlib.util.spec_from_file_location("helm_manifest_generator", ENGINE_PATH)
engine = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(engine)


CONFIGURATION = engine.GeneratorConfiguration(
    component_name="Katib",
    kustomize_path=Path("applications/katib/helm/kustomize"),
    output_path=Path("applications/katib/helm/manifests"),
    generator_script="scripts/generate-katib-helm-manifests.py",
    synchronize_script="scripts/synchronize-katib-manifests.sh",
)


def main():
    return engine.command_line(
        CONFIGURATION,
        description="Generate payloads for the Katib Helm chart.",
        default_repository_root=Path(__file__).resolve().parents[1],
    )


if __name__ == "__main__":
    sys.exit(main())
