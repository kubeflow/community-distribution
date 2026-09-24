#!/usr/bin/env python3

import subprocess
import unittest

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INSTALL_HELPER_PATH = REPOSITORY_ROOT / "tests/pipelines_helm_install.sh"


class PipelinesHelmInstallHelperTest(unittest.TestCase):
    def test_helper_waits_for_every_rendered_deployment(self):
        helper_text = INSTALL_HELPER_PATH.read_text()

        self.assertIn(
            "mapfile -t PIPELINES_DEPLOYMENT_NAMES",
            helper_text,
        )
        self.assertIn(
            '$0 == "kind: Deployment"',
            helper_text,
        )
        self.assertNotIn(
            "PIPELINES_DEPLOYMENT_NAMES=(",
            helper_text,
        )

    def test_missing_scenario_returns_usage_error(self):
        self.assertTrue(
            INSTALL_HELPER_PATH.is_file(),
            f"Installation helper does not exist: {INSTALL_HELPER_PATH}",
        )

        result = subprocess.run(
            [INSTALL_HELPER_PATH],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "Usage: pipelines_helm_install.sh <scenario>",
            result.stderr,
        )

    def test_unsupported_scenario_returns_clear_error(self):
        self.assertTrue(
            INSTALL_HELPER_PATH.is_file(),
            f"Installation helper does not exist: {INSTALL_HELPER_PATH}",
        )

        result = subprocess.run(
            [INSTALL_HELPER_PATH, "unsupported"],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn(
            "Unsupported Kubeflow Pipelines scenario: unsupported",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
