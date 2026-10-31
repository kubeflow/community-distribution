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
# Fixture credentials shared with the comparison values files; the credential
# guards refuse to render the shipped placeholders.
VALID_OIDC_CLIENT_SECRET = "pUBnBOY80SnXgjibTYM9ZWNzY2xreNGQok"
VALID_STATIC_PASSWORD_HASH = (
    "$2y$12$4K/VkmDd1q1Orb3xAt82zu8gk7Ad6ReFR4LCP9UeYE90NLiN9Df72"
)


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

        # Only the outer gate may be Helm code. Stripping every directive would
        # let a conditional inside the definition hide part of the schema from
        # this comparison while the rendered definition differs.
        lines = chart_template.splitlines()
        self.assertEqual(lines[0], "{{- if .Values.crds.enabled }}")
        self.assertEqual(lines[-1], "{{- end }}")
        body = "\n".join(lines[1:-1])
        self.assertNotIn(
            "{{", body, "templates/crds.yaml must contain only the outer gate"
        )
        chart = yaml.safe_load(body)
        # The retention annotation is the one intentional difference; everything
        # else, apiVersion, kind, labels and other annotations included, must
        # match the synchronized upstream definition.
        annotations = dict(chart["metadata"].get("annotations", {}))
        self.assertEqual(annotations.pop("helm.sh/resource-policy", None), "keep")
        if annotations:
            chart["metadata"]["annotations"] = annotations
        else:
            chart["metadata"].pop("annotations", None)

        self.assertEqual(
            chart,
            upstream,
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
            "--set-string",
            f"oidcClient.secret={VALID_OIDC_CLIENT_SECRET}",
            "--set-string",
            f"staticPassword.hash={VALID_STATIC_PASSWORD_HASH}",
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
            "common/dex/helm/crds must not exist; Helm preserves the schema from "
            "the first installation indefinitely.",
        )


if __name__ == "__main__":
    unittest.main()
