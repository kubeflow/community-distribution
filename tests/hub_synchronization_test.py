#!/usr/bin/env python3
"""Synchronization must not commit a user's unrelated or hand-written changes.

Use a disposable Git repository and the actual library, generator, chart and
staging helper. Only network fetching is replaced with the checked-in source.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHART_PATHS = (
    Path("applications/hub/helm"),
    Path("applications/hub/helm-catalog"),
)


class HubSynchronizationTest(unittest.TestCase):
    def test_replay_is_idempotent_and_commit_leaves_manual_changes_unstaged(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repository"
            root.mkdir()
            for path in (
                "applications/hub",
                "experimental/helm/charts/hub",
            ):
                shutil.copytree(REPOSITORY_ROOT / path, root / path)
            (root / "scripts").mkdir()
            for path in (
                "README.md",
                "scripts/library.sh",
                "scripts/helm_manifest_generator.py",
                "scripts/generate-hub-registry-helm-manifests.py",
                "scripts/generate-hub-catalog-helm-manifests.py",
                "scripts/synchronize-hub-manifests.sh",
            ):
                shutil.copy2(REPOSITORY_ROOT / path, root / path)
            source = Path(temporary_directory) / "source"
            shutil.copytree(
                root / "applications/hub/upstream",
                source / "hub/manifests/kustomize",
            )
            with (root / "scripts/library.sh").open("a") as library:
                library.write("\nclone_and_checkout() { return 0; }\n")

            def git(*arguments):
                return subprocess.run(
                    ["git", *arguments],
                    cwd=root,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout

            git("init", "-q")
            # The fixture identity is local to this disposable repository;
            # continuous integration does not configure a contributor identity.
            git("config", "user.name", "Synchronization test")
            git("config", "user.email", "synchronization-test@example.invalid")
            git("add", ".")
            git("commit", "-qs", "-m", "Synchronization regression baseline")
            environment = os.environ | {
                "SOURCE_DIRECTORY": str(source),
                "KUBEFLOW_SYNCHRONIZE_NO_COMMIT": "true",
            }

            def synchronize():
                result = subprocess.run(
                    ["bash", "scripts/synchronize-hub-manifests.sh"],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            synchronize()
            first_difference = git("diff", "--binary")
            self.assertEqual(first_difference, "")
            synchronize()
            self.assertEqual(git("diff", "--binary"), first_difference)
            self.assertEqual(git("diff", "--cached"), "")

            for chart_path in CHART_PATHS:
                chart_metadata = root / chart_path / "Chart.yaml"
                metadata = yaml.safe_load(chart_metadata.read_text())
                chart_metadata.write_text(
                    chart_metadata.read_text().replace(
                        f'appVersion: "{metadata["appVersion"]}"',
                        'appVersion: "v0.0.0"',
                    )
                )
                git("add", str(chart_path / "Chart.yaml"))
            git("commit", "-qs", "-m", "Exercise synchronization version repair")
            for chart_path in CHART_PATHS:
                template = root / chart_path / "templates/platform.yaml"
                template.write_text("# manual change\n" + template.read_text())
            (root / "unrelated.txt").write_text("not component-owned\n")
            environment.pop("KUBEFLOW_SYNCHRONIZE_NO_COMMIT")
            synchronize()

            committed = git("show", "--format=", "--name-only", "HEAD").splitlines()
            for chart_path in CHART_PATHS:
                self.assertIn(str(chart_path / "Chart.yaml"), committed)
                self.assertNotIn(str(chart_path / "templates/platform.yaml"), committed)
                self.assertIn(
                    str(chart_path / "templates/platform.yaml"),
                    git("diff", "--name-only"),
                )
            self.assertNotIn("unrelated.txt", committed)
            self.assertIn("Signed-off-by:", git("show", "-s", "--format=%B", "HEAD"))
            self.assertIn("?? unrelated.txt", git("status", "--short"))


if __name__ == "__main__":
    unittest.main()
