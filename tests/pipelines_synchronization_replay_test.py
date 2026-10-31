#!/usr/bin/env python3
"""Tests that every Kubeflow Pipelines chart input selects its synchronization replay."""

import re
import shlex
import subprocess
import sys
import unittest

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REPLAY_SCRIPT = REPOSITORY_ROOT / "tests/resynchronize-upstream-changes.py"
SYNCHRONIZATION_SCRIPT = "scripts/synchronize-pipelines-manifests.sh"

CHART_INPUTS = (
    "applications/pipeline/upstream/base/installs/generic/kustomization.yaml",
    "applications/pipeline/overlays/kustomization.yaml",
    "applications/pipeline/overlays/k8s-native/kustomization.yaml",
    "applications/pipeline/helm/Chart.yaml",
    "applications/pipeline/helm/manifests/common-resources.yaml",
    "scripts/generate-pipelines-helm-manifests.py",
)


def selected_scripts(changed_file: str) -> str:
    completed = subprocess.run(
        [sys.executable, str(REPLAY_SCRIPT), "--dry-run", changed_file],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout


class SynchronizationReplaySelectionTest(unittest.TestCase):
    def test_every_chart_input_selects_the_pipelines_synchronization(self):
        for changed_file in CHART_INPUTS:
            with self.subTest(changed_file=changed_file):
                self.assertIn(
                    f"Running {SYNCHRONIZATION_SCRIPT}...",
                    selected_scripts(changed_file),
                )

    def test_an_unrelated_file_selects_nothing(self):
        self.assertNotIn(
            SYNCHRONIZATION_SCRIPT,
            selected_scripts("applications/pipeline/helm/README.md"),
        )

    def test_integration_workflows_use_the_synchronized_sdk_version(self):
        script = (REPOSITORY_ROOT / SYNCHRONIZATION_SCRIPT).read_text()
        version_match = re.search(
            r'^COMPONENT_VERSION="([^"]+)"$', script, re.MULTILINE
        )
        self.assertIsNotNone(version_match)
        version = version_match.group(1)

        workflow_names = (
            "full_kubeflow_integration_test.yaml",
            "helm-pipelines-test.yaml",
            "helm_kubeflow_integration_test.yaml",
            "pipeline_test.yaml",
            "spark_pipeline_test.yaml",
        )
        for workflow_name in workflow_names:
            with self.subTest(workflow=workflow_name):
                workflow = REPOSITORY_ROOT / ".github/workflows" / workflow_name
                installation_commands = [
                    shlex.split(line.strip())
                    for line in workflow.read_text().splitlines()
                    if "kfp-kubernetes" in line
                    and ("pip3 install" in line or "python3 -m pip install" in line)
                ]
                self.assertEqual(len(installation_commands), 1)
                self.assertIn(f"kfp=={version}", installation_commands[0])
                self.assertIn(f"kfp-kubernetes=={version}", installation_commands[0])


if __name__ == "__main__":
    unittest.main()
