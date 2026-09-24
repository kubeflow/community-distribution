#!/usr/bin/env python3
"""The Katib synchronization commits only the paths that it owns.

A replay with KUBEFLOW_SYNCHRONIZE_NO_COMMIT=true never reaches the staging
code, so these tests run the real script with commits enabled: in a disposable
repository, against a local fixture of the pinned upstream repository, without
network access. A stub stands in for helm; it proves nothing about lint.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from katib_synchronization_patch_test import (
    MYSQL_MANIFEST_PATH,
    REPOSITORY_ROOT,
    script_variable,
    upstream_manifest,
)

SCRIPT_PATH = "scripts/synchronize-katib-manifests.sh"
UPSTREAM_PATH = "applications/katib/upstream"
CHART_PATH = "applications/katib/helm"
BRANCH_NAME = "synchronize-katib-manifests-test"
HELM_STUB = """\
#!/usr/bin/env bash
if [[ "$1" == "version" ]]; then
    echo "v4.0.0"
fi
"""


GIT_ENVIRONMENT = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Synchronization Test",
    "GIT_AUTHOR_EMAIL": "synchronization-test@example.invalid",
    "GIT_COMMITTER_NAME": "Synchronization Test",
    "GIT_COMMITTER_EMAIL": "synchronization-test@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def git(directory, *arguments):
    return subprocess.run(
        ["git", *arguments],
        cwd=directory,
        env=GIT_ENVIRONMENT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


class KatibSynchronizationStagingTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.environment = {
            **GIT_ENVIRONMENT,
            "SOURCE_DIRECTORY": str(root / "source"),
            "BRANCH_NAME": BRANCH_NAME,
        }
        self.environment.pop("KUBEFLOW_SYNCHRONIZE_NO_COMMIT", None)

        stub_directory = root / "stub"
        stub_directory.mkdir()
        helm_stub = stub_directory / "helm"
        helm_stub.write_text(HELM_STUB)
        helm_stub.chmod(0o755)
        self.environment["PATH"] = f"{stub_directory}{os.pathsep}{os.environ['PATH']}"

        self.create_upstream_fixture(root)
        self.repository = root / "manifests"
        self.create_distribution_fixture()

    def create_upstream_fixture(self, root):
        """A local kubeflow/katib with the pinned tag, cloned where the script
        expects its cached clone, so that its fetch needs no network."""
        origin = root / "origin"
        manifests = origin / "manifests/v1beta1"
        shutil.copytree(REPOSITORY_ROOT / UPSTREAM_PATH, manifests)
        (origin / "manifests/v1beta1/components/mysql/mysql.yaml").write_bytes(
            upstream_manifest()
        )
        git(origin, "init", "--quiet")
        git(origin, "add", "--all")
        git(origin, "commit", "--quiet", "--message", "upstream")
        git(origin, "tag", script_variable("COMMIT"))
        (root / "source").mkdir()
        git(root / "source", "clone", "--quiet", str(origin), "katib")

    def create_distribution_fixture(self):
        for path in ("scripts", "applications/katib"):
            shutil.copytree(REPOSITORY_ROOT / path, self.repository / path)
        shutil.copy(REPOSITORY_ROOT / "README.md", self.repository / "README.md")
        # Two differences that the synchronization must repair and commit.
        chart = self.repository / CHART_PATH / "Chart.yaml"
        chart.write_text(
            chart.read_text().replace(
                f'appVersion: "{script_variable("COMMIT")}"', 'appVersion: "v0.0.0"'
            )
        )
        (self.repository / UPSTREAM_PATH / "removed-upstream.yaml").write_text("{}\n")
        git(self.repository, "init", "--quiet")
        git(self.repository, "add", "--all")
        git(self.repository, "commit", "--quiet", "--message", "base")

    def synchronize(self):
        return subprocess.run(
            ["bash", str(self.repository / SCRIPT_PATH)],
            cwd=self.repository,
            env=self.environment,
            capture_output=True,
            text=True,
        )

    def test_commit_holds_only_the_synchronized_paths(self):
        readme = self.repository / CHART_PATH / "README.md"
        readme.write_text(readme.read_text() + "\nAn unrelated local edit.\n")
        sentinel = self.repository / CHART_PATH / "templates/sentinel.yaml"
        sentinel.write_text("{}\n")

        result = self.synchronize()

        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        committed = git(
            self.repository, "show", "--name-only", "--format=", "HEAD"
        ).split()
        self.assertEqual(
            sorted(committed),
            [f"{CHART_PATH}/Chart.yaml", f"{UPSTREAM_PATH}/removed-upstream.yaml"],
        )
        self.assertEqual(
            git(self.repository, "status", "--porcelain").splitlines(),
            [f" M {CHART_PATH}/README.md", f"?? {CHART_PATH}/templates/sentinel.yaml"],
        )
        self.assertEqual(
            (self.repository / MYSQL_MANIFEST_PATH).read_bytes(),
            (REPOSITORY_ROOT / MYSQL_MANIFEST_PATH).read_bytes(),
        )

    def test_content_staged_before_the_run_stops_the_synchronization(self):
        staged = self.repository / "unrelated-staged.yaml"
        staged.write_text("{}\n")
        git(self.repository, "add", staged.name)
        head = git(self.repository, "rev-parse", "HEAD")
        branch = git(self.repository, "branch", "--show-current")

        result = self.synchronize()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not empty", result.stderr)
        self.assertEqual(git(self.repository, "rev-parse", "HEAD"), head)
        self.assertEqual(git(self.repository, "branch", "--show-current"), branch)
        self.assertEqual(
            git(self.repository, "status", "--porcelain").splitlines(),
            [f"A  {staged.name}"],
        )


if __name__ == "__main__":
    unittest.main()
