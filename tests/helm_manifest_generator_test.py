#!/usr/bin/env python3
"""Tests for the shared Helm manifest generation engine.

These use a synthetic component configuration so they stay independent of any
one chart. Component-specific selector behaviour is tested beside its chart.
"""

import copy
import importlib.util
import os
import stat
import subprocess
import tempfile
import unittest

from pathlib import Path
from unittest import mock

from ruamel.yaml import YAML

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = REPOSITORY_ROOT / "scripts/helm_manifest_generator.py"

_SPEC = importlib.util.spec_from_file_location("helm_manifest_generator", ENGINE_PATH)
engine = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(engine)

CRDS_PAYLOAD = "platform-crds.yaml"
RESOURCES_PAYLOAD = "platform-resources.yaml"
DOCUMENT = "documents/example.json"


def configuration():
    return engine.GeneratorConfiguration(
        component_name="Example",
        kustomize_path=Path("applications/example/helm/kustomize"),
        output_path=Path("applications/example/helm/manifests"),
        generator_script="scripts/generate-example-helm-manifests.py",
        synchronize_script="scripts/synchronize-example-manifests.sh",
        hand_written_resources=(
            ("Deployment", "example", False),
            ("ConfigMap", "example-parameters-", True),
        ),
        extracted_documents=(
            ("ConfigMap", "example-parameters-", True, "payload", "example.json"),
        ),
    )


class HelmManifestGeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.yaml = YAML(typ="safe")

    def resource(
        self, name, kind="ConfigMap", api_version="v1", namespace="kubeflow", data=None
    ):
        metadata = {"name": name}
        if namespace is not None:
            metadata["namespace"] = namespace
        resource = {"apiVersion": api_version, "kind": kind, "metadata": metadata}
        if data is not None:
            resource["data"] = data
        return resource

    def resources(self):
        return [
            self.resource("example", kind="Deployment", api_version="apps/v1"),
            self.resource(
                "example-parameters-deadbeef12", data={"payload": '{"a": 1}'}
            ),
            self.resource(
                "examples.kubeflow.org",
                kind="CustomResourceDefinition",
                api_version="apiextensions.k8s.io/v1",
                namespace=None,
            ),
            self.resource("example-service"),
        ]

    # --- identity -------------------------------------------------------

    def test_resource_identity_contains_api_kind_namespace_and_name(self):
        identity = engine.resource_identity(self.resource("example-service"))
        self.assertEqual(identity, ("v1", "ConfigMap", "kubeflow", "example-service"))

    def test_missing_identity_fields_fail(self):
        valid = self.resource("example-service")
        for path in [("apiVersion",), ("kind",), ("metadata",), ("metadata", "name")]:
            resource = copy.deepcopy(valid)
            if len(path) == 1:
                del resource[path[0]]
            else:
                del resource[path[0]][path[1]]
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "identity"):
                    engine.resource_identity(resource)

    def test_duplicate_resource_identities_fail(self):
        resources = self.resources()
        resources.append(copy.deepcopy(resources[-1]))
        with self.assertRaisesRegex(ValueError, "duplicate resource identity"):
            engine.generate_payload_contents(resources, configuration())

    def test_duplicate_resource_across_api_versions_fails(self):
        resources = self.resources()
        beta = copy.deepcopy(resources[0])
        beta["apiVersion"] = "apps/v1beta1"
        resources.append(beta)
        with self.assertRaisesRegex(ValueError, "duplicate resource identity"):
            engine.generate_payload_contents(resources, configuration())

    # --- selection ------------------------------------------------------

    def test_payloads_are_split_only_by_custom_resource_definition(self):
        payloads = engine.generate_payload_contents(self.resources(), configuration())
        self.assertEqual(set(payloads), {CRDS_PAYLOAD, RESOURCES_PAYLOAD, DOCUMENT})

    def test_hand_written_resources_are_excluded_from_payloads(self):
        payloads = engine.generate_payload_contents(self.resources(), configuration())
        rendered = payloads[CRDS_PAYLOAD] + payloads[RESOURCES_PAYLOAD]
        self.assertNotIn("name: example\n", rendered)
        self.assertNotIn("example-parameters-", rendered)

    def test_orphaned_hand_written_resource_fails(self):
        resources = [r for r in self.resources() if r["metadata"]["name"] != "example"]
        with self.assertRaisesRegex(ValueError, "orphaned"):
            engine.generate_payload_contents(resources, configuration())

    def test_generated_name_prefix_requires_a_valid_kustomize_hash(self):
        resources = self.resources()
        for resource in resources:
            if resource["metadata"]["name"].startswith("example-parameters-"):
                resource["metadata"]["name"] = "example-parameters-not-a-hash"
        with self.assertRaisesRegex(ValueError, "orphaned"):
            engine.generate_payload_contents(resources, configuration())

    def test_empty_payload_fails(self):
        resources = [
            r for r in self.resources() if r["kind"] != "CustomResourceDefinition"
        ]
        with self.assertRaisesRegex(ValueError, "empty"):
            engine.generate_payload_contents(resources, configuration())

    # --- content --------------------------------------------------------

    def test_crd_retention_is_added_without_mutating_input(self):
        resources = self.resources()
        original = copy.deepcopy(resources)
        payloads = engine.generate_payload_contents(resources, configuration())
        crd = next(self.yaml.load_all(payloads[CRDS_PAYLOAD]))
        self.assertEqual(
            crd["metadata"]["annotations"]["helm.sh/resource-policy"], "keep"
        )
        self.assertEqual(resources, original)

    def test_non_crd_resources_are_not_changed(self):
        resources = self.resources()
        expected = copy.deepcopy(resources[-1])
        payloads = engine.generate_payload_contents(resources, configuration())
        self.assertIn(expected, list(self.yaml.load_all(payloads[RESOURCES_PAYLOAD])))

    def test_upstream_block_scalar_style_is_preserved(self):
        rendered = (
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n"
            "  name: example-service\n  namespace: kubeflow\n"
            'data:\n  body: |-\n    {\n      "a": 1\n    }\n'
        )
        resources = self.resources()
        resources[-1] = engine.parse_resources(rendered)[0]
        payloads = engine.generate_payload_contents(resources, configuration())
        self.assertIn("  body: |-\n    {\n", payloads[RESOURCES_PAYLOAD])

    def test_documents_are_extracted_verbatim_with_a_trailing_newline(self):
        payloads = engine.generate_payload_contents(self.resources(), configuration())
        self.assertEqual(payloads[DOCUMENT], '{"a": 1}\n')

    def test_documents_carry_no_generated_header(self):
        payloads = engine.generate_payload_contents(self.resources(), configuration())
        self.assertFalse(payloads[DOCUMENT].startswith("#"))

    def test_missing_document_data_key_fails(self):
        resources = self.resources()
        for resource in resources:
            if resource["metadata"]["name"].startswith("example-parameters-"):
                del resource["data"]["payload"]
        with self.assertRaisesRegex(ValueError, "missing data key"):
            engine.generate_payload_contents(resources, configuration())

    def test_empty_document_data_key_fails(self):
        resources = self.resources()
        for resource in resources:
            if resource["metadata"]["name"].startswith("example-parameters-"):
                resource["data"]["payload"] = "  "
        with self.assertRaisesRegex(ValueError, "empty"):
            engine.generate_payload_contents(resources, configuration())

    def test_payload_headers_identify_source_and_regeneration_command(self):
        payloads = engine.generate_payload_contents(self.resources(), configuration())
        for name in [CRDS_PAYLOAD, RESOURCES_PAYLOAD]:
            with self.subTest(payload=name):
                self.assertTrue(
                    payloads[name].startswith(
                        "# Code generated by "
                        "scripts/generate-example-helm-manifests.py. DO NOT EDIT.\n"
                        "# Source: kustomize build "
                        "applications/example/helm/kustomize\n"
                        "# Regenerate with: KUBEFLOW_SYNCHRONIZE_NO_COMMIT=true "
                        "./scripts/synchronize-example-manifests.sh\n"
                    )
                )

    def test_generation_is_byte_for_byte_deterministic(self):
        resources = self.resources()
        self.assertEqual(
            engine.generate_payload_contents(resources, configuration()),
            engine.generate_payload_contents(resources, configuration()),
        )

    # --- atomic replacement ---------------------------------------------

    def test_existing_directory_mode_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / "manifests"
            output_directory.mkdir(mode=0o755)
            os.chmod(output_directory, 0o755)

            engine.write_payloads_atomically(
                output_directory,
                {"current.yaml": "current\n", "documents/nested.json": "{}\n"},
            )

            self.assertEqual(stat.S_IMODE(output_directory.stat().st_mode), 0o755)
            self.assertEqual(
                stat.S_IMODE((output_directory / "documents").stat().st_mode), 0o755
            )

    def test_new_directory_uses_a_readable_default_mode(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / "manifests"

            engine.write_payloads_atomically(output_directory, {"a.yaml": "a\n"})

            self.assertEqual(
                stat.S_IMODE(output_directory.stat().st_mode),
                engine.DEFAULT_DIRECTORY_MODE,
            )

    def test_failed_atomic_replacement_restores_previous_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / "manifests"
            output_directory.mkdir()
            existing = output_directory / "existing.yaml"
            existing.write_text("existing\n")
            original_replace = engine.os.replace
            attempts = 0

            def fail_first_replacement(source, destination):
                nonlocal attempts
                if Path(destination) == output_directory:
                    attempts += 1
                    if attempts == 1:
                        raise OSError("simulated replacement failure")
                return original_replace(source, destination)

            with mock.patch.object(
                engine.os, "replace", side_effect=fail_first_replacement
            ):
                with self.assertRaisesRegex(OSError, "simulated replacement failure"):
                    engine.write_payloads_atomically(
                        output_directory, {"replacement.yaml": "replacement\n"}
                    )

            self.assertEqual(existing.read_text(), "existing\n")
            self.assertFalse((output_directory / "replacement.yaml").exists())

    def test_successful_replacement_removes_stale_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / "manifests"
            output_directory.mkdir()
            (output_directory / "stale.yaml").write_text("stale\n")

            engine.write_payloads_atomically(
                output_directory,
                {"current.yaml": "current\n", "documents/nested.json": "{}\n"},
            )

            self.assertFalse((output_directory / "stale.yaml").exists())
            self.assertEqual(
                (output_directory / "current.yaml").read_text(), "current\n"
            )
            self.assertEqual(
                (output_directory / "documents/nested.json").read_text(), "{}\n"
            )

    def test_payload_filename_must_not_escape_the_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory) / "manifests"
            for filename in ["../escape.yaml", "a/b/c.yaml", "/absolute.yaml"]:
                with self.subTest(filename=filename):
                    with self.assertRaises(ValueError):
                        engine.write_payloads_atomically(
                            output_directory, {filename: "content\n"}
                        )

    def test_kustomize_is_built_once_from_the_configured_path(self):
        yaml = YAML()
        with tempfile.TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            render_path = repository_root / "render.yaml"
            with render_path.open("w") as stream:
                yaml.dump_all(self.resources(), stream)
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=render_path.read_text(), stderr=""
            )

            with mock.patch.object(
                engine.subprocess, "run", return_value=completed
            ) as run:
                engine.generate_manifests(repository_root, configuration())

            run.assert_called_once()
            self.assertEqual(
                run.call_args.args[0],
                ["kustomize", "build", "applications/example/helm/kustomize"],
            )

    def test_failed_kustomize_build_is_reported(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="boom"
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            with mock.patch.object(engine.subprocess, "run", return_value=completed):
                with self.assertRaisesRegex(RuntimeError, "Kustomize build failed"):
                    engine.generate_manifests(temporary_directory, configuration())


if __name__ == "__main__":
    unittest.main()
