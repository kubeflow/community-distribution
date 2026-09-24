#!/usr/bin/env python3
"""Generate Knative Eventing core payloads; its retained Namespace is hoisted.

The shared engine retains definitions and omits aggregation-controller-owned
empty ClusterRole rules. No broker/channel bundles are added to the baseline.
"""

import sys
from pathlib import Path

from helm_manifest_generator import GeneratorConfiguration, command_line

CONFIGURATION = GeneratorConfiguration(
    component_name="Knative Eventing",
    kustomize_path=Path("common/knative/knative-eventing/helm/kustomize"),
    output_path=Path("common/knative/knative-eventing/helm/manifests"),
    generator_script="scripts/generate-knative-eventing-helm-manifests.py",
    synchronize_script="scripts/synchronize-knative-manifests.sh",
    hand_written_resources=(("Namespace", "knative-eventing", False),),
)

if __name__ == "__main__":
    sys.exit(command_line(CONFIGURATION, __doc__, Path(__file__).resolve().parents[1]))
