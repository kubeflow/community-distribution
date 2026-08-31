#!/usr/bin/env python3
"""Behaviour of the Kubeflow Notebooks Helm chart."""

import shutil
import subprocess
import tempfile
import unittest

from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHART_PATH = REPOSITORY_ROOT / "applications/notebooks-v1/helm"
RESOURCES_PAYLOAD = "manifests/platform-resources.yaml"
OWNED_NAMESPACE = "kubeflow"


def render_chart(chart_directory=CHART_PATH, *arguments, namespace=OWNED_NAMESPACE):
    return subprocess.run(
        [
            "helm",
            "template",
            "kubeflow-notebooks",
            str(chart_directory),
            "--namespace",
            namespace,
            *arguments,
        ],
        capture_output=True,
        text=True,
    )


def load_manifests(rendered):
    return [document for document in yaml.safe_load_all(rendered) if document]


class NotebooksHelmChartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = render_chart()
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.manifests = load_manifests(result.stdout)

    def test_chart_refuses_a_foreign_namespace(self):
        result = render_chart(CHART_PATH, namespace="not-kubeflow")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be installed into the kubeflow namespace", result.stderr)

    def test_upstream_template_delimiters_are_not_evaluated(self):
        """The payload is data, not chart code.

        Rendering it through the template engine would silently resolve an
        upstream expression to the empty string. The Notebook Controller exists
        to template pod specifications, so upstream shipping a Go template
        delimiter is a matter of time.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            chart_directory = Path(temporary_directory) / "chart"
            shutil.copytree(CHART_PATH, chart_directory)
            with (chart_directory / RESOURCES_PAYLOAD).open("a") as stream:
                stream.write(
                    "---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n"
                    "  name: literal-template-expression\n  namespace: kubeflow\n"
                    "data:\n"
                    '  template: "{{ .Values.notebookName }}-workspace"\n'
                )

            result = render_chart(chart_directory)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                'template: "{{ .Values.notebookName }}-workspace"', result.stdout
            )

    def test_missing_or_empty_payload_fails_the_render(self):
        for state in ["missing", "empty", "comments"]:
            with self.subTest(state=state):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    chart_directory = Path(temporary_directory) / "chart"
                    shutil.copytree(CHART_PATH, chart_directory)
                    payload = chart_directory / RESOURCES_PAYLOAD
                    if state == "missing":
                        payload.unlink()
                    elif state == "empty":
                        payload.write_text("")
                    else:
                        payload.write_text("# generated payload\n")

                    result = render_chart(chart_directory)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("missing or empty", result.stderr)

    def test_custom_resource_definitions_are_retained_and_optional(self):
        definitions = [
            manifest
            for manifest in self.manifests
            if manifest["kind"] == "CustomResourceDefinition"
        ]
        self.assertEqual(len(definitions), 3)
        for definition in definitions:
            self.assertEqual(
                definition["metadata"]["annotations"]["helm.sh/resource-policy"],
                "keep",
            )

        result = render_chart(
            CHART_PATH, "--set", "customResourceDefinitions.enabled=false"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        remaining = load_manifests(result.stdout)

        self.assertEqual(
            [m for m in remaining if m["kind"] == "CustomResourceDefinition"], []
        )
        self.assertEqual(len(remaining), len(self.manifests) - 3)

    def test_every_resource_declares_the_owned_namespace(self):
        namespaces = {
            manifest["metadata"].get("namespace")
            for manifest in self.manifests
            if manifest["metadata"].get("namespace")
        }

        self.assertEqual(namespaces, {OWNED_NAMESPACE})


if __name__ == "__main__":
    unittest.main()
