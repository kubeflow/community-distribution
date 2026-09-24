#!/usr/bin/env python3
"""Every generated Helm payload must be what its generator produces today.

The payloads under applications/*/helm/manifests are committed files that
Helm reads with .Files.Get. Parity compares them semantically with Kustomize,
and the upstream replay runs the synchronization scripts for changed paths;
neither proves that the committed bytes are the generator's current output.
The --check mode of every generator does, without writing, and this test
proves --check itself: it sees an edited input, a changed byte, a missing or
extra file, and it never modifies the output directory.
"""

import contextlib
import importlib.util
import io
import os
import shlex
import subprocess
import tempfile
import unittest

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = REPOSITORY_ROOT / "scripts/helm_manifest_generator.py"
_SPEC = importlib.util.spec_from_file_location("helm_manifest_generator", ENGINE_PATH)
engine = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(engine)

GENERATOR_GLOB = "scripts/generate-*-helm-manifests.py"
KNOWN_GENERATORS = {
    "scripts/generate-dashboard-helm-manifests.py",
    "scripts/generate-kserve-helm-manifests.py",
    "scripts/generate-kserve-ui-helm-manifests.py",
    "scripts/generate-notebooks-v1-helm-manifests.py",
    "scripts/generate-knative-serving-helm-manifests.py",
    "scripts/generate-workspaces-helm-manifests.py",
}

CONFIGURATION = engine.GeneratorConfiguration(
    component_name="Example",
    kustomize_path=Path("applications/example/helm/kustomize"),
    output_path=Path("applications/example/helm/manifests"),
    generator_script="scripts/generate-example-helm-manifests.py",
    synchronize_script="scripts/synchronize-example-manifests.sh",
    extracted_documents=(
        ("ConfigMap", "example-parameters", False, "payload", "example.json"),
    ),
    hand_written_resources=(("ConfigMap", "example-parameters", False),),
)

KUSTOMIZE_INPUT = """\
apiVersion: v1
kind: ConfigMap
metadata:
  name: example-parameters
  namespace: kubeflow
data:
  payload: '{"a": 1}'
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: example
  namespace: kubeflow
  labels:
    app: example
---
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: examples.kubeflow.org
spec:
  group: kubeflow.org
  names:
    kind: Example
    plural: examples
  scope: Namespaced
  versions: []
"""


def write_fixture_repository(root):
    kustomize_directory = root / CONFIGURATION.kustomize_path
    kustomize_directory.mkdir(parents=True)
    (kustomize_directory / "resources.yaml").write_text(KUSTOMIZE_INPUT)
    (kustomize_directory / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
        "resources:\n- resources.yaml\n"
    )
    return kustomize_directory / "resources.yaml"


def snapshot(directory):
    """Everything --check could disturb: entries, inodes, times and bytes."""
    entries = {}
    for path in [directory, *directory.rglob("*")]:
        status = path.stat()
        entries[str(path)] = (
            status.st_ino,
            status.st_mtime_ns,
            None if path.is_dir() else path.read_bytes(),
        )
    siblings = sorted(str(path) for path in directory.parent.iterdir())
    return entries, siblings


def run_command_line(root, *arguments):
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        status = engine.command_line(
            CONFIGURATION, "Generate Example payloads.", root, list(arguments)
        )
    return status, stdout.getvalue(), stderr.getvalue()


class FreshnessCheckTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input_path = write_fixture_repository(self.root)
        self.output_directory = self.root / CONFIGURATION.output_path
        engine.generate_manifests(self.root, CONFIGURATION)

    def check(self):
        return engine.check_manifests(self.root, CONFIGURATION)

    def test_freshly_generated_payloads_are_fresh(self):
        self.assertEqual(self.check(), [])
        self.assertEqual(
            sorted(path.name for path in self.output_directory.rglob("*.*")),
            ["example.json", "platform-crds.yaml", "platform-resources.yaml"],
        )

    def test_an_edited_input_is_detected_and_the_repair_restores_freshness(self):
        """The case the replay selection can miss: a local input changes and
        nobody regenerates. The advertised repair is the generator itself."""
        self.input_path.write_text(
            self.input_path.read_text().replace("app: example", "app: renamed")
        )

        self.assertEqual(self.check(), [("stale", "platform-resources.yaml")])

        status, stdout, _ = run_command_line(self.root)
        self.assertEqual(status, 0)
        self.assertEqual(stdout, "Generated 3 Example resources across 3 files.\n")
        self.assertEqual(self.check(), [])

    def test_a_single_changed_byte_is_stale(self):
        path = self.output_directory / "platform-crds.yaml"
        path.write_bytes(path.read_bytes().replace(b"keep", b"Keep", 1))

        self.assertEqual(self.check(), [("stale", "platform-crds.yaml")])

    def test_a_line_ending_change_is_stale(self):
        """read_text would normalise CRLF away; the bytes Helm packages differ."""
        path = self.output_directory / "documents/example.json"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

        self.assertEqual(self.check(), [("stale", "documents/example.json")])

    def test_missing_and_extra_files_are_reported_including_documents(self):
        (self.output_directory / "documents/example.json").unlink()
        (self.output_directory / "documents/other.json").write_text("{}\n")
        (self.output_directory / "stray.yaml").write_text("kind: Stray\n")

        self.assertEqual(
            self.check(),
            [
                ("missing", "documents/example.json"),
                ("extra", "documents/other.json"),
                ("extra", "stray.yaml"),
            ],
        )

    def test_a_missing_output_directory_reports_every_file_missing(self):
        for path in sorted(self.output_directory.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        self.output_directory.rmdir()

        self.assertEqual(
            [status for status, _ in self.check()], ["missing", "missing", "missing"]
        )

    def test_check_never_writes(self):
        """On a fresh, a stale and a failing tree alike: no file, inode,
        modification time or staging directory changes."""
        fresh = snapshot(self.output_directory)
        self.assertEqual(self.check(), [])
        self.assertEqual(snapshot(self.output_directory), fresh)

        self.input_path.write_text(self.input_path.read_text() + "---\n")
        (self.output_directory / "stray.yaml").write_text("kind: Stray\n")
        stale = snapshot(self.output_directory)
        self.assertNotEqual(self.check(), [])
        self.assertEqual(snapshot(self.output_directory), stale)

        (self.input_path.parent / "kustomization.yaml").write_text("resources: [\n")
        with self.assertRaisesRegex(RuntimeError, "Kustomize build failed"):
            self.check()
        self.assertEqual(snapshot(self.output_directory), stale)

    def test_the_command_line_reports_differences_and_the_local_repair(self):
        (self.output_directory / "platform-resources.yaml").unlink()

        status, stdout, stderr = run_command_line(self.root, "--check")

        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertIn("missing  platform-resources.yaml", stderr)
        self.assertIn(
            "Regenerate with: python3 scripts/generate-example-helm-manifests.py\n",
            stderr,
        )
        self.assertNotIn("synchronize", stderr)

    def test_the_advertised_repair_runs_with_an_explicit_repository_root(self):
        """The printed command is executed as printed, from a repository whose
        path contains spaces, so quoting is part of the contract."""
        root = self.root / "repository with spaces"
        input_path = write_fixture_repository(root)
        engine.generate_manifests(root, CONFIGURATION)
        entry_point = root / CONFIGURATION.generator_script
        entry_point.parent.mkdir()
        entry_point.write_text(
            "import sys\nfrom pathlib import Path\n"
            f"sys.path.insert(0, {str(Path(__file__).parent)!r})\n"
            "from helm_payload_freshness_test import engine, CONFIGURATION\n"
            'sys.exit(engine.command_line(CONFIGURATION, "fixture", Path.cwd()))\n'
        )
        input_path.write_text(input_path.read_text().replace("app: example", "app: x"))

        # A relative root, as typed from the parent directory: the advertised
        # repair must still work from the repository root itself.
        previous_directory = Path.cwd()
        os.chdir(self.root)
        try:
            status, _, stderr = run_command_line(
                root, "--check", "--repository-root", "repository with spaces"
            )
        finally:
            os.chdir(previous_directory)
        self.assertEqual(status, 1)
        advertised = next(
            line.split(": ", 1)[1]
            for line in stderr.splitlines()
            if line.startswith("Regenerate with: ")
        )
        self.assertIn(f"--repository-root {shlex.quote(str(root))}", advertised)

        repaired = subprocess.run(
            shlex.split(advertised), cwd=root, capture_output=True, text=True
        )

        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual(engine.check_manifests(root, CONFIGURATION), [])

    def test_the_command_line_reports_a_fresh_tree_with_status_zero(self):
        status, stdout, stderr = run_command_line(self.root, "--check")

        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(
            stdout,
            "Example payloads in applications/example/helm/manifests are fresh.\n",
        )

    def test_a_render_failure_is_an_error_status_in_both_modes(self):
        (self.input_path.parent / "kustomization.yaml").write_text("resources: [\n")

        for mode in ([], ["--check"]):
            with self.subTest(mode=mode):
                status, stdout, stderr = run_command_line(self.root, *mode)
                self.assertEqual((status, stdout), (1, ""))
                self.assertIn("ERROR: Example Kustomize build failed", stderr)


class RepositoryPayloadsTest(unittest.TestCase):
    """The committed payloads of every generator in this checkout are fresh."""

    def test_every_generator_is_discovered(self):
        found = {
            str(path.relative_to(REPOSITORY_ROOT))
            for path in REPOSITORY_ROOT.glob(GENERATOR_GLOB)
        }
        self.assertTrue(KNOWN_GENERATORS <= found, found)

    def test_every_committed_payload_is_fresh(self):
        for generator in sorted(REPOSITORY_ROOT.glob(GENERATOR_GLOB)):
            with self.subTest(generator=generator.name):
                result = subprocess.run(
                    ["python3", str(generator), "--check"],
                    cwd=REPOSITORY_ROOT,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("are fresh", result.stdout)


if __name__ == "__main__":
    unittest.main()
