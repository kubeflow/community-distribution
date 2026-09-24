#!/usr/bin/env python3
"""The Katib synchronization reapplies one distribution patch, strictly.

scripts/synchronize-katib-manifests.sh imports the pinned upstream manifests and
then reapplies the distribution's deviation in the MySQL manifest from a
committed patch. These tests source the script for apply_katib_mysql_patch and
run it against a disposable directory, without network access.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SYNCHRONIZATION_SCRIPT = REPOSITORY_ROOT / "scripts/synchronize-katib-manifests.sh"
MYSQL_MANIFEST_PATH = "applications/katib/upstream/components/mysql/mysql.yaml"
MYSQL_PATCH_PATH = "applications/katib/patches/mysql-image-and-probes.patch"
EXTRA_TARGET_PATCH = """\
diff --git a/applications/katib/upstream/components/mysql/pvc.yaml b/applications/katib/upstream/components/mysql/pvc.yaml
--- a/applications/katib/upstream/components/mysql/pvc.yaml
+++ b/applications/katib/upstream/components/mysql/pvc.yaml
@@ -1 +1 @@
-storage: 10Gi
+storage: 20Gi
"""


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def script_variable(name):
    for line in SYNCHRONIZATION_SCRIPT.read_text().splitlines():
        if line.startswith(f'{name}="'):
            return line.split('"')[1]
    raise AssertionError(f"{name} is not set in {SYNCHRONIZATION_SCRIPT}")


def upstream_manifest():
    """The manifest as imported: the committed file with the patch reversed.

    The reverse application exists only here, to rebuild the input without
    network access. The synchronization script never reverses a patch.
    """
    with tempfile.TemporaryDirectory() as temporary_directory:
        manifest = Path(temporary_directory) / MYSQL_MANIFEST_PATH
        manifest.parent.mkdir(parents=True)
        shutil.copy(REPOSITORY_ROOT / MYSQL_MANIFEST_PATH, manifest)
        subprocess.run(
            ["git", "apply", "--reverse", str(REPOSITORY_ROOT / MYSQL_PATCH_PATH)],
            cwd=temporary_directory,
            env={
                **os.environ,
                "GIT_CEILING_DIRECTORIES": str(Path(temporary_directory).parent),
            },
            check=True,
        )
        return manifest.read_bytes()


class KatibSynchronizationPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = upstream_manifest()
        cls.patched = (REPOSITORY_ROOT / MYSQL_MANIFEST_PATH).read_bytes()

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.manifests_directory = root / "manifests"
        self.foreign_directory = root / "foreign"
        self.manifest = self.manifests_directory / MYSQL_MANIFEST_PATH
        self.patch = self.manifests_directory / MYSQL_PATCH_PATH
        self.manifest.parent.mkdir(parents=True)
        self.patch.parent.mkdir(parents=True)
        self.manifest.write_bytes(self.upstream)
        shutil.copy(REPOSITORY_ROOT / MYSQL_PATCH_PATH, self.patch)
        for directory in (self.manifests_directory, self.foreign_directory):
            directory.mkdir(exist_ok=True)
            subprocess.run(["git", "init", "--quiet"], cwd=directory, check=True)

    def apply_patch(self, overrides=""):
        """Run the function from a foreign repository, as the script does after
        clone_and_checkout has changed the directory into the upstream clone."""
        return subprocess.run(
            [
                "bash",
                "-c",
                f'source "$1"; {overrides} apply_katib_mysql_patch "$2"',
                "bash",
                str(SYNCHRONIZATION_SCRIPT),
                str(self.manifests_directory),
            ],
            cwd=self.foreign_directory,
            capture_output=True,
            text=True,
        )

    def assert_rejected(self, result, message, expected_bytes):
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(message, result.stderr)
        self.assertEqual(self.manifest.read_bytes(), expected_bytes)
        self.assert_nothing_else_changed()

    def assert_nothing_else_changed(self):
        leftovers = [
            path.name
            for path in self.manifest.parent.iterdir()
            if path != self.manifest
        ]
        self.assertEqual(leftovers, [])
        for directory in (self.manifests_directory, self.foreign_directory):
            staged = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=directory,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(staged.stdout, "")
        self.assertEqual(
            [path.name for path in self.foreign_directory.iterdir()], [".git"]
        )

    def test_recorded_digests_match_the_committed_files(self):
        self.assertEqual(
            sha256(self.upstream), script_variable("MYSQL_MANIFEST_UPSTREAM_SHA256")
        )
        self.assertEqual(
            sha256(self.patched), script_variable("MYSQL_MANIFEST_PATCHED_SHA256")
        )

    def test_expected_input_becomes_the_committed_manifest(self):
        result = self.apply_patch()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.manifest.read_bytes(), self.patched)
        self.assert_nothing_else_changed()

    def test_changed_upstream_input_is_rejected(self):
        inputs = {
            "one changed byte": self.upstream.replace(b"mysql:8.0.29", b"mysql:8.0.30"),
            "shifted context": b"# a new upstream comment\n" + self.upstream,
            "patch already applied": self.patched,
        }
        for description, content in inputs.items():
            with self.subTest(description):
                self.manifest.write_bytes(content)

                result = self.apply_patch()

                self.assert_rejected(result, "is not the input that", content)

    def test_patch_that_does_not_apply_is_rejected(self):
        content = self.upstream.replace(b"mysql:8.0.29", b"mysql:8.0.30")
        self.manifest.write_bytes(content)

        result = self.apply_patch(
            f'MYSQL_MANIFEST_UPSTREAM_SHA256="{sha256(content)}";'
        )

        self.assert_rejected(result, "did not apply", content)

    def test_unexpected_result_leaves_the_imported_manifest(self):
        result = self.apply_patch(f'MYSQL_MANIFEST_PATCHED_SHA256="{"0" * 64}";')

        self.assert_rejected(result, "differs from the reviewed result", self.upstream)

    def test_patch_with_a_second_target_is_rejected(self):
        with self.patch.open("a") as patch:
            patch.write(EXTRA_TARGET_PATCH)

        result = self.apply_patch()

        self.assert_rejected(result, "must change exactly", self.upstream)


if __name__ == "__main__":
    unittest.main()
