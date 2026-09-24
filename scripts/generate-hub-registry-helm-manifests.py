#!/usr/bin/env python3
"""Generate Hub model registry payloads with the shared engine.

Only source credential Secrets are hoisted into templates for supplied values.
"""

import importlib.util
import sys

from pathlib import Path

ENGINE_PATH = Path(__file__).resolve().parent / "helm_manifest_generator.py"
_SPEC = importlib.util.spec_from_file_location("helm_manifest_generator", ENGINE_PATH)
engine = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(engine)


CONFIGURATION = engine.GeneratorConfiguration(
    component_name="Hub model registry",
    kustomize_path=Path("applications/hub/helm/kustomize"),
    output_path=Path("applications/hub/helm/manifests"),
    generator_script="scripts/generate-hub-registry-helm-manifests.py",
    synchronize_script="scripts/synchronize-hub-manifests.sh",
    crds_payload_filename=None,
    hand_written_resources=(("Secret", "model-registry-db-secrets", False),),
    extracted_documents=(
        (
            "Secret",
            "model-registry-db-secrets",
            False,
            "POSTGRES_USER",
            "database-username.txt",
        ),
    ),
)


def main():
    return engine.command_line(
        CONFIGURATION,
        description="Generate payloads for the Kubeflow Hub model registry Helm chart.",
        default_repository_root=Path(__file__).resolve().parents[1],
    )


if __name__ == "__main__":
    sys.exit(main())
