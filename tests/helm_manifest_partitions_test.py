#!/usr/bin/env python3
"""Shared generator partitions must preserve identities and fail closed."""

import importlib.util
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "helm_manifest_generator", ROOT / "scripts/helm_manifest_generator.py"
)
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


def resource(kind, name, api_version="v1"):
    return {"apiVersion": api_version, "kind": kind, "metadata": {"name": name}}


def configuration(**options):
    return engine.GeneratorConfiguration(
        component_name="Example",
        kustomize_path=Path("baseline"),
        output_path=Path("output"),
        generator_script="generator.py",
        synchronize_script="synchronize.sh",
        **options,
    )


class PartitionGenerationTest(unittest.TestCase):
    def test_definition_only_partition_retains_every_definition(self):
        resources = [
            resource("CustomResourceDefinition", name, "apiextensions.k8s.io/v1")
            for name in ("ones.example.org", "twos.example.org")
        ] + [resource("ConfigMap", "configuration")]
        payloads = engine.generate_payload_contents(
            resources,
            configuration(
                included_resource_kinds=(
                    ("apiextensions.k8s.io", "CustomResourceDefinition"),
                ),
                crds_payload_directory="definitions",
                resources_payload_filename=None,
            ),
        )
        self.assertEqual(
            set(payloads),
            {"definitions/ones.example.org.yaml", "definitions/twos.example.org.yaml"},
        )
        for payload in payloads.values():
            definition = yaml.safe_load(payload)
            self.assertEqual(
                definition["metadata"]["annotations"]["helm.sh/resource-policy"], "keep"
            )

    def test_selection_uses_group_and_kind_not_kind_alone(self):
        payloads = engine.generate_payload_contents(
            [
                resource("Runtime", "selected", "example.org/v1"),
                resource("Runtime", "foreign", "other.org/v1"),
            ],
            configuration(
                included_resource_kinds=(("example.org", "Runtime"),),
                crds_payload_filename=None,
            ),
        )
        self.assertEqual(
            yaml.safe_load(payloads["platform-resources.yaml"])["metadata"]["name"],
            "selected",
        )

    def test_excluded_kinds_do_not_leak_into_control_plane(self):
        payloads = engine.generate_payload_contents(
            [
                resource("Runtime", "catalog", "example.org/v1"),
                resource("ConfigMap", "controller"),
            ],
            configuration(
                excluded_resource_kinds=(("example.org", "Runtime"),),
                crds_payload_filename=None,
            ),
        )
        self.assertEqual(
            yaml.safe_load(payloads["platform-resources.yaml"])["kind"], "ConfigMap"
        )

    def test_disabling_output_does_not_silently_discard_selected_resources(self):
        with self.assertRaisesRegex(ValueError, "no payload destination"):
            engine.generate_payload_contents(
                [resource("ConfigMap", "controller")],
                configuration(resources_payload_filename=None),
            )

    def test_empty_selected_partition_fails(self):
        with self.assertRaisesRegex(ValueError, "empty"):
            engine.generate_payload_contents(
                [resource("ConfigMap", "controller")],
                configuration(
                    included_resource_kinds=(("example.org", "Runtime"),),
                    crds_payload_filename=None,
                ),
            )

    def test_duplicate_identity_outside_partition_still_fails(self):
        duplicate = resource("ConfigMap", "duplicate")
        with self.assertRaisesRegex(ValueError, "duplicate resource identity"):
            engine.generate_payload_contents(
                [duplicate, duplicate],
                configuration(
                    included_resource_kinds=(("example.org", "Runtime"),),
                    crds_payload_filename=None,
                ),
            )


if __name__ == "__main__":
    unittest.main()
