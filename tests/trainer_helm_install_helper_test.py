#!/usr/bin/env python3
"""The ordered installer must stop before later releases on readiness failure."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_CHART_DIRECTORY = "applications/trainer/helm-crds"
API_INSTALLATION = (
    "helm install trainer-apis {chart} --namespace kubeflow-system --wait --timeout 5m"
)
PREAMBLE = [
    "helm version --template {{.Version}}",
    "kubectl get namespace kubeflow-system",
]
RELEASES = ["trainer-apis", "trainer", "trainer-runtimes"]


class TrainerInstallerTest(unittest.TestCase):
    def run_installer(
        self, failure="", arguments=(), variables=None, working_directory=None
    ):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            log = directory / "commands"
            log.touch()
            stub = """#!/usr/bin/env python3
import os, pathlib, sys
command = pathlib.Path(sys.argv[0]).name + " " + " ".join(sys.argv[1:])
with open(os.environ["COMMAND_LOG"], "a") as log: log.write(command + "\\n")
if sys.argv[1:2] == ["version"]: print("v4.2.2")
if os.environ.get("FAIL_COMMAND") and os.environ["FAIL_COMMAND"] in command: sys.exit(1)
"""
            for name in ("helm", "kubectl"):
                executable = directory / name
                executable.write_text(stub)
                executable.chmod(0o755)
            environment = {
                name: value
                for name, value in os.environ.items()
                if name != "TRAINER_APIS_CHART"
            } | {
                "PATH": f"{directory}:{os.environ['PATH']}",
                "COMMAND_LOG": str(log),
                "FAIL_COMMAND": failure,
            }
            result = subprocess.run(
                ["bash", str(ROOT / "tests/trainer_helm_install.sh"), *arguments],
                env=environment | (variables or {}),
                cwd=working_directory,
                text=True,
                capture_output=True,
            )
            return result, log.read_text().splitlines()

    def complete_installation(self):
        result, commands = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        return commands

    def release_commands(self, commands):
        """The commands of every release: its installation up to the next one."""
        starts = [
            index
            for index, command in enumerate(commands)
            if command.startswith("helm install ")
        ]
        return {
            commands[start].split()[2]: commands[start:end]
            for start, end in zip(starts, starts[1:] + [len(commands)])
        }

    def test_definitions_then_controller_then_catalog_after_readiness(self):
        result, commands = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        installs = [
            command for command in commands if command.startswith("helm install")
        ]
        self.assertEqual(
            [command.split()[2] for command in installs],
            ["trainer-apis", "trainer", "trainer-runtimes"],
        )
        controller = commands.index(installs[1])
        catalog = commands.index(installs[2])
        established = [
            index
            for index, command in enumerate(commands)
            if "--for=condition=Established" in command
        ]
        self.assertEqual(len(established), 4)
        self.assertLess(max(established), controller)
        readiness = [
            index
            for index, command in enumerate(commands)
            if "caBundle" in command or "endpoints/" in command
        ]
        self.assertEqual(len(readiness), 6)
        self.assertTrue(all(controller < index < catalog for index in readiness))

    def test_failed_definition_establishment_prevents_controller_and_catalog(self):
        result, commands = self.run_installer("--for=condition=Established")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(
            any(command.startswith("helm install trainer ") for command in commands)
        )
        self.assertFalse(
            any(
                command.startswith("helm install trainer-runtimes ")
                for command in commands
            )
        )

    def test_failed_webhook_readiness_prevents_catalog(self):
        result, commands = self.run_installer("caBundle")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(
            any(
                command.startswith("helm install trainer-runtimes ")
                for command in commands
            )
        )

    def test_default_installs_the_api_release_from_the_chart_directory(self):
        commands = self.complete_installation()
        self.assertEqual(commands[:2], PREAMBLE)
        self.assertEqual(
            commands[2], API_INSTALLATION.format(chart=API_CHART_DIRECTORY)
        )

    def test_api_chart_variable_changes_only_the_api_release_chart(self):
        default = self.complete_installation()
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary).resolve() / "trainer-apis-0.1.0.tgz"
            package.touch()
            result, commands = self.run_installer(
                variables={"TRAINER_APIS_CHART": str(package)}
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = [
            command.replace(f" {API_CHART_DIRECTORY} ", f" {package} ")
            for command in default
        ]
        self.assertNotEqual(expected, default)
        self.assertEqual(commands, expected)
        self.assertEqual(
            [command for command in commands if str(package) in command],
            [API_INSTALLATION.format(chart=package)],
        )

    def test_relative_api_chart_is_resolved_against_the_calling_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            (directory / "packages").mkdir()
            package = directory / "packages/trainer-apis-0.1.0.tgz"
            package.touch()
            result, commands = self.run_installer(
                variables={"TRAINER_APIS_CHART": "packages/trainer-apis-0.1.0.tgz"},
                working_directory=directory,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(API_INSTALLATION.format(chart=package), commands)

    def test_missing_api_chart_fails_before_any_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "trainer-apis-0.1.0.tgz"
            result, commands = self.run_installer(
                variables={"TRAINER_APIS_CHART": str(missing)}
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands, [])
        self.assertIn(
            f"TRAINER_APIS_CHART names {missing}, which does not exist", result.stderr
        )

    def test_a_named_release_is_installed_with_its_part_of_the_complete_sequence(self):
        complete = self.complete_installation()
        by_release = self.release_commands(complete)
        self.assertEqual(list(by_release), RELEASES)
        self.assertEqual(
            complete, PREAMBLE + sum((by_release[name] for name in RELEASES), [])
        )
        for release in RELEASES:
            with self.subTest(release=release):
                result, commands = self.run_installer(arguments=[release])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(commands, PREAMBLE + by_release[release])

    def test_named_releases_are_installed_in_the_order_of_the_installer(self):
        by_release = self.release_commands(self.complete_installation())
        result, commands = self.run_installer(
            arguments=["trainer-runtimes", "trainer-apis"]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            commands,
            PREAMBLE + by_release["trainer-apis"] + by_release["trainer-runtimes"],
        )

    def test_api_chart_variable_applies_to_a_named_api_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary).resolve() / "trainer-apis-0.1.0.tgz"
            package.touch()
            result, commands = self.run_installer(
                arguments=["trainer-apis"],
                variables={"TRAINER_APIS_CHART": str(package)},
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands[2], API_INSTALLATION.format(chart=package))

    def test_unknown_release_fails_before_any_call(self):
        result, commands = self.run_installer(arguments=["trainer", "trainer-api"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands, [])
        self.assertIn("trainer-api is not one of", result.stderr)


if __name__ == "__main__":
    unittest.main()
