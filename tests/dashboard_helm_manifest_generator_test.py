#!/usr/bin/env python3
"""Dashboard-specific generator behaviour.

The component-independent engine is covered by tests/helm_manifest_generator_test.py.
What is asserted here is the Dashboard configuration itself: that its selectors
match what Kustomize actually renders, and that the chart consumes the result.
"""

import importlib.util
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = REPOSITORY_ROOT / "scripts/generate-dashboard-helm-manifests.py"
CHART_PATH = REPOSITORY_ROOT / "applications/dashboard/helm"

CRDS_PAYLOAD = "platform-crds.yaml"
RESOURCES_PAYLOAD = "platform-resources.yaml"
LINKS_DOCUMENT = "documents/dashboard-links.json"
SETTINGS_DOCUMENT = "documents/dashboard-settings.json"
NAMESPACE_LABELS_DOCUMENT = "documents/profile-namespace-labels.yaml"

_SPEC = importlib.util.spec_from_file_location(
    "generate_dashboard_helm_manifests", GENERATOR_PATH
)
generator = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(generator)


def render_chart(chart_directory, *arguments):
    return subprocess.run(
        [
            "helm",
            "template",
            "kubeflow-dashboard",
            str(chart_directory),
            "--namespace",
            "kubeflow",
            *arguments,
        ],
        capture_output=True,
        text=True,
    )


class DashboardGeneratorConfigurationTest(unittest.TestCase):
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

    def test_every_selector_matches_exactly_one_rendered_resource(self):
        for selector in generator.CONFIGURATION.hand_written_resources:
            with self.subTest(selector=selector):
                matches = [
                    resource
                    for resource in self.resources
                    if generator.engine.matches_selector(resource, *selector)
                ]
                self.assertEqual(len(matches), 1)

    def test_payloads_and_documents_are_generated_for_the_real_overlay(self):
        payloads = generator.engine.generate_payload_contents(
            self.resources, generator.CONFIGURATION
        )

        self.assertEqual(
            set(payloads),
            {
                CRDS_PAYLOAD,
                RESOURCES_PAYLOAD,
                LINKS_DOCUMENT,
                SETTINGS_DOCUMENT,
                NAMESPACE_LABELS_DOCUMENT,
            },
        )

    def test_hand_written_resources_are_not_also_vendored(self):
        payloads = generator.engine.generate_payload_contents(
            self.resources, generator.CONFIGURATION
        )
        vendored = [
            resource
            for payload in [CRDS_PAYLOAD, RESOURCES_PAYLOAD]
            for resource in generator.engine.parse_resources(payloads[payload])
        ]

        for selector in generator.CONFIGURATION.hand_written_resources:
            with self.subTest(selector=selector):
                self.assertFalse(
                    any(
                        generator.engine.matches_selector(resource, *selector)
                        for resource in vendored
                    )
                )

    def test_every_rendered_resource_is_either_vendored_or_hand_written(self):
        payloads = generator.engine.generate_payload_contents(
            self.resources, generator.CONFIGURATION
        )
        vendored = [
            resource
            for payload in [CRDS_PAYLOAD, RESOURCES_PAYLOAD]
            for resource in generator.engine.parse_resources(payloads[payload])
        ]
        hand_written = [
            resource
            for resource in self.resources
            if any(
                generator.engine.matches_selector(resource, *selector)
                for selector in generator.CONFIGURATION.hand_written_resources
            )
        ]

        self.assertEqual(len(vendored) + len(hand_written), len(self.resources))
        self.assertEqual(
            len(hand_written), len(generator.CONFIGURATION.hand_written_resources)
        )


class DashboardChartConsumesPayloadsTest(unittest.TestCase):
    """The chart must fail closed when a generated file is missing."""

    def test_literal_helm_template_expression_remains_literal(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            chart_directory = Path(temporary_directory) / "chart"
            shutil.copytree(CHART_PATH, chart_directory)
            with (chart_directory / "manifests" / RESOURCES_PAYLOAD).open(
                "a"
            ) as stream:
                stream.write(
                    "---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n"
                    "  name: literal-template-expression\ndata:\n"
                    '  value: "{{ upstream.value }}"\n'
                )

            result = render_chart(chart_directory)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('value: "{{ upstream.value }}"', result.stdout)

    def test_missing_or_empty_payload_fails_the_render(self):
        for state in ["missing", "empty", "comments", "separator"]:
            with self.subTest(state=state):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    chart_directory = Path(temporary_directory) / "chart"
                    shutil.copytree(CHART_PATH, chart_directory)
                    payload = chart_directory / "manifests" / RESOURCES_PAYLOAD
                    if state == "missing":
                        payload.unlink()
                    elif state == "empty":
                        payload.write_text("")
                    elif state == "comments":
                        payload.write_text("# generated payload\n")
                    else:
                        payload.write_text("---\n")

                    result = render_chart(chart_directory)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("missing or empty", result.stderr)

    def test_missing_document_fails_the_render(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            chart_directory = Path(temporary_directory) / "chart"
            shutil.copytree(CHART_PATH, chart_directory)
            (chart_directory / "manifests" / LINKS_DOCUMENT).unlink()

            result = render_chart(chart_directory)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing or empty", result.stderr)

    def test_packaged_chart_contains_every_generated_file(self):
        expected = {
            f"kubeflow-dashboard/manifests/{name}"
            for name in [
                CRDS_PAYLOAD,
                RESOURCES_PAYLOAD,
                LINKS_DOCUMENT,
                SETTINGS_DOCUMENT,
                NAMESPACE_LABELS_DOCUMENT,
            ]
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = subprocess.run(
                [
                    "helm",
                    "package",
                    str(CHART_PATH),
                    "--destination",
                    temporary_directory,
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            package = next(Path(temporary_directory).glob("*.tgz"))
            with tarfile.open(package, "r:gz") as archive:
                packaged = set(archive.getnames())
            self.assertTrue(expected.issubset(packaged))


if __name__ == "__main__":
    unittest.main()
