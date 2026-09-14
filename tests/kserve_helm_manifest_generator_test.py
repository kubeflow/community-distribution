#!/usr/bin/env python3
"""KServe-specific generator behaviour.

The component-independent engine is covered by tests/helm_manifest_generator_test.py.
What is asserted here is the KServe configuration itself: that its exclusion
matches what Kustomize actually renders and that the payloads carry the
component's decisions.
"""

import importlib.util
import subprocess
import unittest

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = REPOSITORY_ROOT / "scripts/generate-kserve-helm-manifests.py"
CHART_PATH = REPOSITORY_ROOT / "applications/kserve/kserve/helm"

CRDS_PAYLOAD_DIRECTORY = "custom-resource-definitions/"
RESOURCES_PAYLOAD = "platform-resources.yaml"

_SPEC = importlib.util.spec_from_file_location(
    "generate_kserve_helm_manifests", GENERATOR_PATH
)
generator = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(generator)


class KServeGeneratorConfigurationTest(unittest.TestCase):
    """The configuration must match what Kustomize actually renders."""

    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            ["kustomize", "build", str(generator.CONFIGURATION.kustomize_path)],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.resources = generator.engine.parse_resources(result.stdout)
        cls.payloads = generator.engine.generate_payload_contents(
            cls.resources, generator.CONFIGURATION
        )

    def test_the_excluded_namespace_is_rendered_by_kustomize_exactly_once(self):
        namespaces = [
            resource for resource in self.resources if resource["kind"] == "Namespace"
        ]

        self.assertEqual(len(namespaces), 1)
        self.assertEqual(namespaces[0]["metadata"]["name"], "kserve")
        self.assertEqual(
            generator.CONFIGURATION.excluded_resources, (("Namespace", "kserve"),)
        )

    def test_payloads_carry_everything_but_the_namespace(self):
        definitions = "".join(
            contents
            for filename, contents in self.payloads.items()
            if filename.startswith(CRDS_PAYLOAD_DIRECTORY)
        )
        rendered = definitions + self.payloads[RESOURCES_PAYLOAD]

        self.assertNotIn("kind: Namespace\n", rendered)
        self.assertEqual(rendered.count("\nkind: "), len(self.resources) - 1)
        self.assertEqual(
            definitions.count("helm.sh/resource-policy: keep"),
            definitions.count("kind: CustomResourceDefinition"),
        )

    def test_every_definition_payload_stays_under_the_helm_file_size_limit(self):
        for filename, contents in self.payloads.items():
            with self.subTest(payload=filename):
                self.assertLess(len(contents.encode()), 5 * 1024 * 1024)

    def test_checked_in_payloads_are_current(self):
        """The committed payloads equal a fresh generation, byte for byte."""
        for filename, contents in self.payloads.items():
            with self.subTest(payload=filename):
                self.assertEqual(
                    (CHART_PATH / "manifests" / filename).read_text(), contents
                )


if __name__ == "__main__":
    unittest.main()
