#!/usr/bin/env python3
"""The Trainer synchronization must stage only the paths that it owns.

scripts/synchronize-trainer-manifests.sh ends in commit_changes, which runs
"git add" on every path argument and then commits. The upstream replay sets
KUBEFLOW_SYNCHRONIZE_NO_COMMIT, which returns before "git add", so the replay
cannot observe what a maintainer's run stages. This test runs the real script
in a disposable repository that holds a copy of the three Trainer charts. Only
the steps that need the network, Helm or Kustomize are replaced. The path list,
copy_manifests, update_readme, update_helm_chart_application_version and
commit_changes are the real ones, so the test cannot drift from the script.
"""

import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LIBRARY_PATH = REPOSITORY_ROOT / "scripts/library.sh"
SYNCHRONIZATION_SCRIPT = "scripts/synchronize-trainer-manifests.sh"
GENERATOR_SCRIPT = "scripts/generate-trainer-helm-manifests.py"
UPSTREAM = "applications/trainer/upstream"
CHART_DIRECTORIES = (
    "applications/trainer/helm-crds",
    "applications/trainer/helm",
    "applications/trainer/helm-runtimes",
)
INTERNAL_DEPENDENCY = "applications/trainer/helm-crds/charts/trainer-api-payload"
DEFINITIONS = f"{INTERNAL_DEPENDENCY}/manifests/definitions"
PREVIOUS_VERSION = "v0.0.0"

CHART_FILES = tuple(
    f"{directory}/Chart.yaml" for directory in (*CHART_DIRECTORIES, INTERNAL_DEPENDENCY)
)
REMOVED_DEFINITION = f"{DEFINITIONS}/jobsets.jobset.x-k8s.io.yaml"
REGENERATED_DEFINITION = f"{DEFINITIONS}/trainjobs.trainer.kubeflow.org.yaml"
ADDED_DEFINITION = f"{DEFINITIONS}/examples.example.org.yaml"
REGENERATED_PAYLOADS = (
    "applications/trainer/helm/manifests/platform-resources.yaml",
    "applications/trainer/helm-runtimes/manifests/platform-resources.yaml",
)

# Hand-written files that a maintainer happens to have edited, and files that
# were never tracked. Neither belongs to a synchronization commit.
UNRELATED_EDITED_FILES = (
    "applications/trainer/helm-crds/ci/comparison.yaml",
    "applications/trainer/helm-crds/values.yaml",
    f"{INTERNAL_DEPENDENCY}/templates/definitions.yaml",
    f"{INTERNAL_DEPENDENCY}/values.yaml",
    "applications/trainer/helm/README.md",
    "applications/trainer/helm/ci/comparison.yaml",
    "applications/trainer/helm/templates/resources.yaml",
    "applications/trainer/helm-runtimes/ci/comparison.yaml",
    "applications/trainer/helm-runtimes/templates/resources.yaml",
)
UNTRACKED_SENTINELS = (
    "applications/trainer/helm-crds/untracked-note.md",
    "applications/trainer/helm-crds/ci/untracked-values.yaml",
    f"{INTERNAL_DEPENDENCY}/untracked-note.md",
    f"{INTERNAL_DEPENDENCY}/templates/untracked-template.yaml",
    "applications/trainer/helm/untracked-note.md",
    "applications/trainer/helm/templates/untracked-template.yaml",
    "applications/trainer/helm-runtimes/ci/untracked-values.yaml",
)

OWNED_CHANGES = {
    ("M", "README.md"),
    ("M", GENERATOR_SCRIPT),
    ("M", SYNCHRONIZATION_SCRIPT),
    ("A", f"{UPSTREAM}/base/added.yaml"),
    ("M", f"{UPSTREAM}/base/kustomization.yaml"),
    ("D", f"{UPSTREAM}/base/removed.yaml"),
    ("A", ADDED_DEFINITION),
    ("D", REMOVED_DEFINITION),
    ("M", REGENERATED_DEFINITION),
    *(("M", payload) for payload in REGENERATED_PAYLOADS),
    *(("M", chart_file) for chart_file in CHART_FILES),
}

# The real library, with only the steps that need the network, Helm or
# Kustomize replaced. The test writes what the generator would have written.
LIBRARY_WITHOUT_EXTERNAL_TOOLS = f"""\
source {shlex.quote(str(LIBRARY_PATH))}
clone_and_checkout() {{ :; }}
require_helm_major_version() {{ :; }}
helm() {{ :; }}
python3() {{ :; }}
"""


def append_line(path, line):
    with path.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


class SynchronizationRun:
    """One run of the real synchronization script in a disposable repository."""

    def __init__(self, directory, no_commit=False):
        self.repository = Path(directory) / "repository"
        self.source = Path(directory) / "source"
        self.environment = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith("GIT_") and name != "KUBEFLOW_SYNCHRONIZE_NO_COMMIT"
        } | {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "Synchronization Test",
            "GIT_AUTHOR_EMAIL": "synchronization-test@example.org",
            "GIT_COMMITTER_NAME": "Synchronization Test",
            "GIT_COMMITTER_EMAIL": "synchronization-test@example.org",
            "SOURCE_DIRECTORY": str(self.source),
        }
        if no_commit:
            self.environment["KUBEFLOW_SYNCHRONIZE_NO_COMMIT"] = "true"

        self.create_previous_synchronization()
        self.write_generator_output_and_maintainer_edits()
        self.write_unrelated_changes()
        self.initial_branch = self.git("branch", "--show-current").strip()
        self.result = subprocess.run(
            ["bash", str(self.repository / SYNCHRONIZATION_SCRIPT)],
            cwd=self.repository,
            env=self.environment,
            capture_output=True,
            text=True,
        )

    def git(self, *arguments):
        return subprocess.run(
            ["git", *arguments],
            cwd=self.repository,
            env=self.environment,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def write(self, relative_path, contents):
        path = self.repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def create_previous_synchronization(self):
        """Commit the charts as the synchronization of a previous version."""
        for directory in CHART_DIRECTORIES:
            shutil.copytree(REPOSITORY_ROOT / directory, self.repository / directory)
        for chart_file in self.repository.rglob("Chart.yaml"):
            chart_file.write_text(
                re.sub(
                    r"(?m)^appVersion:.*$",
                    f'appVersion: "{PREVIOUS_VERSION}"',
                    chart_file.read_text(encoding="utf-8"),
                ),
                encoding="utf-8",
            )
        self.write(f"{UPSTREAM}/base/kustomization.yaml", "resources: []\n")
        self.write(f"{UPSTREAM}/base/removed.yaml", "kind: Removed\n")
        self.write(
            "README.md",
            f"| Trainer | {UPSTREAM} | [{PREVIOUS_VERSION}](https://github.com/"
            f"kubeflow/trainer/tree/{PREVIOUS_VERSION}/manifests) |\n",
        )
        self.write("scripts/library.sh", LIBRARY_WITHOUT_EXTERNAL_TOOLS)
        self.write(
            GENERATOR_SCRIPT,
            (REPOSITORY_ROOT / GENERATOR_SCRIPT).read_text(encoding="utf-8"),
        )
        self.write(
            SYNCHRONIZATION_SCRIPT,
            (REPOSITORY_ROOT / SYNCHRONIZATION_SCRIPT).read_text(encoding="utf-8")
            + "# A maintainer edits this script to select the next version.\n",
        )
        self.git("init", "--quiet")
        self.git("add", "--all")
        self.git("commit", "--quiet", "--message", "Previous synchronization")

    def write_generator_output_and_maintainer_edits(self):
        """Write what the replaced steps and the maintainer would have written."""
        manifests = self.source / "trainer/manifests/base"
        manifests.mkdir(parents=True)
        (manifests / "kustomization.yaml").write_text("resources: [added.yaml]\n")
        (manifests / "added.yaml").write_text("kind: Added\n")

        (self.repository / REMOVED_DEFINITION).unlink()
        self.write(ADDED_DEFINITION, "kind: CustomResourceDefinition\n")
        for payload in (REGENERATED_DEFINITION, *REGENERATED_PAYLOADS):
            append_line(self.repository / payload, "# regenerated")

        append_line(self.repository / GENERATOR_SCRIPT, "# corrected")
        self.write(
            SYNCHRONIZATION_SCRIPT,
            (REPOSITORY_ROOT / SYNCHRONIZATION_SCRIPT).read_text(encoding="utf-8"),
        )

    def write_unrelated_changes(self):
        for edited_file in UNRELATED_EDITED_FILES:
            append_line(self.repository / edited_file, "# unrelated edit")
        for sentinel in UNTRACKED_SENTINELS:
            self.write(sentinel, "unrelated\n")

    def commit_count(self):
        return int(self.git("rev-list", "--count", "HEAD"))

    def committed_changes(self):
        lines = self.git(
            "show", "--no-renames", "--name-status", "--format=", "HEAD"
        ).splitlines()
        return {tuple(line.split("\t", 1)) for line in lines}

    def staged_paths(self):
        return self.git("diff", "--cached", "--name-only").splitlines()

    def remaining_changes(self):
        lines = self.git("status", "--porcelain", "--untracked-files=all").splitlines()
        return {(line[:2].strip(), line[3:]) for line in lines}


class TrainerSynchronizationStagingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.synchronization = SynchronizationRun(directory.name)
        cls.committed = cls.synchronization.committed_changes()
        cls.remaining = cls.synchronization.remaining_changes()

    def test_synchronization_creates_exactly_one_commit(self):
        result = self.synchronization.result
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.synchronization.commit_count(), 2)
        self.assertEqual(self.synchronization.staged_paths(), [])

    def test_application_version_of_every_chart_is_staged(self):
        for chart_file in CHART_FILES:
            with self.subTest(chart_file=chart_file):
                self.assertNotIn(
                    f'appVersion: "{PREVIOUS_VERSION}"',
                    self.synchronization.git("show", f"HEAD:{chart_file}"),
                )

    def test_commit_holds_exactly_the_owned_changes(self):
        self.assertEqual(self.committed, OWNED_CHANGES)
        self.assertEqual(
            self.remaining,
            {("M", edited_file) for edited_file in UNRELATED_EDITED_FILES}
            | {("??", sentinel) for sentinel in UNTRACKED_SENTINELS},
        )


class TrainerSynchronizationNoCommitTest(unittest.TestCase):
    def test_no_commit_mode_neither_stages_nor_commits(self):
        with tempfile.TemporaryDirectory() as directory:
            run = SynchronizationRun(directory, no_commit=True)

            self.assertEqual(run.result.returncode, 0, run.result.stderr)
            self.assertEqual(run.commit_count(), 1)
            self.assertEqual(run.staged_paths(), [])
            self.assertEqual(
                run.git("branch", "--show-current").strip(), run.initial_branch
            )
            for chart_file in CHART_FILES:
                self.assertIn(("M", chart_file), run.remaining_changes())


if __name__ == "__main__":
    unittest.main()
