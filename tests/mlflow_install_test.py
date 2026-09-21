#!/usr/bin/env python3
"""Exercise installation rendering and diagnostics without a Kubernetes cluster."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMMAND = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

arguments = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a") as stream:
    stream.write(json.dumps(arguments) + "\n")
if arguments[0] == "apply":
    Path(os.environ["RENDERED_MANIFESTS"]).write_text(sys.stdin.read())
if arguments[:2] == ["rollout", "status"]:
    sys.exit(int(os.environ.get("ROLLOUT_STATUS", "0")))
"""


class MLflowInstallTest(unittest.TestCase):
    def run_installation(self, image=None, rollout_status=0):
        before = set(REPOSITORY_ROOT.glob(".mlflow-install.*"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = root / "kubectl"
            command.write_text(COMMAND)
            command.chmod(0o755)
            command_log = root / "commands.jsonl"
            manifests = root / "resources.yaml"
            environment = dict(os.environ)
            environment.pop("MLFLOW_TEST_IMAGE", None)
            if image is not None:
                environment["MLFLOW_TEST_IMAGE"] = image
            result = subprocess.run(
                ["bash", str(REPOSITORY_ROOT / "tests/mlflow_install.sh")],
                env={
                    **environment,
                    "PATH": f"{directory}:{os.environ['PATH']}",
                    "COMMAND_LOG": str(command_log),
                    "RENDERED_MANIFESTS": str(manifests),
                    "ROLLOUT_STATUS": str(rollout_status),
                },
                capture_output=True,
                text=True,
                timeout=30,
            )
            resources = list(yaml.safe_load_all(manifests.read_text()))
            commands = [
                json.loads(line) for line in command_log.read_text().splitlines()
            ]
        self.assertEqual(before, set(REPOSITORY_ROOT.glob(".mlflow-install.*")))
        container = next(
            resource for resource in resources if resource["kind"] == "Deployment"
        )["spec"]["template"]["spec"]["containers"][0]
        return result, container, commands

    def test_default_installation_keeps_the_declared_release_image(self):
        result, container, _ = self.run_installation()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "ghcr.io/kubeflow/mlflow-integration:v1.6.0", container["image"]
        )
        self.assertEqual("IfNotPresent", container["imagePullPolicy"])

    def test_source_image_is_explicit_and_cannot_be_pulled(self):
        result, container, commands = self.run_installation("mlflow-test:source")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("mlflow-test:source", container["image"])
        self.assertEqual("Never", container["imagePullPolicy"])
        self.assertIn("--app-name=kubernetes-auth", container["args"])
        self.assertTrue(
            any(command[:2] == ["rollout", "status"] for command in commands)
        )

    def test_failed_rollout_reports_diagnostics_and_still_fails(self):
        result, _, commands = self.run_installation("mlflow-test:source", 1)
        self.assertNotEqual(0, result.returncode)
        self.assertTrue(
            any(command[:2] == ["describe", "pods"] for command in commands)
        )
        log_commands = [command for command in commands if command[0] == "logs"]
        self.assertEqual(2, len(log_commands))
        self.assertTrue(any("--previous" in command for command in log_commands))
        self.assertTrue(
            all("--all-containers=true" in command for command in log_commands)
        )

    def test_workflow_builds_and_loads_the_pinned_source_before_installation(self):
        workflow = yaml.load(
            (
                REPOSITORY_ROOT
                / ".github/workflows/full_kubeflow_integration_test.yaml"
            ).read_text(),
            Loader=yaml.BaseLoader,
        )
        steps = workflow["jobs"]["full_kubeflow_integration_test"]["steps"]
        checkout = next(
            step for step in steps if step["name"] == "Checkout MLflow source"
        )
        revision = checkout["with"]["ref"]
        self.assertRegex(revision, r"^[0-9a-f]{40}$")
        self.assertEqual("kubeflow/mlflow-integration", checkout["with"]["repository"])
        self.assertEqual("false", checkout["with"]["persist-credentials"])
        build = next(step for step in steps if step.get("id") == "mlflow-image")
        self.assertEqual(
            f"mlflow-integration:{revision}", build["env"]["MLFLOW_TEST_IMAGE"]
        )
        self.assertIn(
            'docker build --tag "$MLFLOW_TEST_IMAGE" .mlflow-source', build["run"]
        )
        self.assertIn(
            'kind load docker-image "$MLFLOW_TEST_IMAGE" --name kubeflow', build["run"]
        )
        installation = next(step for step in steps if step["name"] == "Install MLflow")
        self.assertEqual(
            "${{ steps.mlflow-image.outputs.image }}",
            installation["env"]["MLFLOW_TEST_IMAGE"],
        )
        self.assertIn("python3 tests/mlflow_install_test.py", installation["run"])
        self.assertLess(steps.index(checkout), steps.index(build))
        self.assertLess(steps.index(build), steps.index(installation))


if __name__ == "__main__":
    unittest.main()
