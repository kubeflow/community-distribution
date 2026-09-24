#!/usr/bin/env python3
"""Tests that every Kubeflow Pipelines chart input selects its synchronization replay."""

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


if __name__ == "__main__":
    unittest.main()
