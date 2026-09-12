#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
CHART_DIRECTORY = ROOT_DIRECTORY / "common" / "dex" / "helm"
UPSTREAM_CUSTOM_RESOURCE_DEFINITION = (
    ROOT_DIRECTORY / "common" / "dex" / "base" / "upstream" / "crds.yaml"
)
HELM_BINARY = os.environ.get("HELM_BINARY", "helm")
CUSTOM_RESOURCE_DEFINITION_NAME = "authcodes.dex.coreos.com"
RETENTION_ANNOTATION = "helm.sh/resource-policy"


def load_custom_resource_definitions(documents):
    return [
        document
        for document in documents
        if document and document.get("kind") == "CustomResourceDefinition"
    ]


class ChartCustomResourceDefinitionMatchesUpstreamTest(unittest.TestCase):
    """The chart copy is hand-written, so upstream drift must fail loudly."""

    def test_chart_specification_matches_the_synchronized_upstream_file(self):
        upstream = yaml.safe_load(UPSTREAM_CUSTOM_RESOURCE_DEFINITION.read_text())
        chart_template = (CHART_DIRECTORY / "templates" / "crds.yaml").read_text()

        body = "\n".join(
            line for line in chart_template.splitlines() if not line.startswith("{{-")
        )
        chart = yaml.safe_load(body)

        self.assertEqual(chart["metadata"]["name"], upstream["metadata"]["name"])
        self.assertEqual(
            chart["spec"],
            upstream["spec"],
            "common/dex/helm/templates/crds.yaml has drifted from the upstream "
            "CustomResourceDefinition synchronized into "
            "common/dex/base/upstream/crds.yaml. Update the chart template.",
        )


class DexCustomResourceDefinitionLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helm_plugins = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.helm_plugins.cleanup()

    def render_manifests(self, *values, include_custom_resource_definitions=False):
        command = [
            HELM_BINARY,
            "template",
            "dex",
            str(CHART_DIRECTORY),
            "--namespace",
            "auth",
        ]
        if include_custom_resource_definitions:
            command.append("--include-crds")
        for value in values:
            command.extend(["--set", value])

        environment = os.environ.copy()
        environment["HELM_PLUGINS"] = self.helm_plugins.name
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, env=environment
        )
        return list(yaml.safe_load_all(result.stdout))

    def test_custom_resource_definition_renders_without_the_include_flag(self):
        """A crds directory needs --include-crds; templates/ does not.

        Rendering with `helm template` and piping into `kubectl apply` is a
        documented installation path, and it previously produced no
        CustomResourceDefinition at all.
        """
        definitions = load_custom_resource_definitions(self.render_manifests())

        self.assertEqual(len(definitions), 1)
        self.assertEqual(
            definitions[0]["metadata"]["name"], CUSTOM_RESOURCE_DEFINITION_NAME
        )

    def test_custom_resource_definition_is_retained_on_uninstall(self):
        definitions = load_custom_resource_definitions(self.render_manifests())

        annotations = definitions[0]["metadata"].get("annotations", {})
        self.assertEqual(annotations.get(RETENTION_ANNOTATION), "keep")

    def test_custom_resource_definition_can_be_disabled(self):
        definitions = load_custom_resource_definitions(
            self.render_manifests("crds.enabled=false")
        )

        self.assertEqual(definitions, [])

    def test_chart_carries_no_crds_directory(self):
        """Helm never upgrades or deletes anything in a chart's crds directory."""
        self.assertFalse(
            (CHART_DIRECTORY / "crds").exists(),
            "common/dex/helm/crds must not exist; Helm freezes those resources at "
            "first-install schema forever.",
        )


if __name__ == "__main__":
    unittest.main()
