#!/usr/bin/env python3
"""Behaviour of the KServe Helm chart that rendered comparison cannot prove."""

import os
import shutil
import subprocess
import tempfile
import unittest

from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHART_PATH = REPOSITORY_ROOT / "applications/kserve/kserve/helm"
CRDS_PAYLOAD = "manifests/platform-crds.yaml"
RESOURCES_PAYLOAD = "manifests/platform-resources.yaml"
OWNED_NAMESPACE = "kserve"
CUSTOM_RESOURCE_DEFINITION_COUNT = 16
# Helm stores the packaged chart, gzip plus base64, in a release Secret that
# must stay well under the Kubernetes object size limit.
PACKAGED_CHART_SIZE_LIMIT = 1_000_000
HELM_BINARY = os.environ.get("HELM_BINARY", "helm")


def render_chart(chart_directory=CHART_PATH, *arguments, namespace=OWNED_NAMESPACE):
    return subprocess.run(
        [
            HELM_BINARY,
            "template",
            "kserve",
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


class KServeHelmChartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = render_chart()
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.rendered = result.stdout
        cls.manifests = load_manifests(result.stdout)

    def test_chart_refuses_a_foreign_namespace(self):
        result = render_chart(CHART_PATH, namespace="not-kserve")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be installed into the kserve namespace", result.stderr)

    def test_upstream_template_delimiters_survive_the_render(self):
        """The payload is data, not chart code.

        The inference service configuration and every ClusterServingRuntime
        carry Go template expressions that KServe itself evaluates. Rendering
        them through the Helm template engine would resolve them to empty
        strings and silently break path-based routing.
        """
        configuration = next(
            manifest
            for manifest in self.manifests
            if manifest["kind"] == "ConfigMap"
            and manifest["metadata"]["name"] == "inferenceservice-config"
        )

        self.assertIn(
            "/serving/{{ .Namespace }}/{{ .Name }}", configuration["data"]["ingress"]
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
        self.assertEqual(len(definitions), CUSTOM_RESOURCE_DEFINITION_COUNT)
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
        self.assertEqual(
            len(remaining), len(self.manifests) - CUSTOM_RESOURCE_DEFINITION_COUNT
        )

    def test_first_revision_renders_only_custom_resource_definitions(self):
        result = render_chart(CHART_PATH, "--set", "resources.enabled=false")
        self.assertEqual(result.returncode, 0, result.stderr)

        kinds = {manifest["kind"] for manifest in load_manifests(result.stdout)}

        self.assertEqual(kinds, {"CustomResourceDefinition"})

    def test_disabling_everything_fails(self):
        result = render_chart(
            CHART_PATH,
            "--set",
            "customResourceDefinitions.enabled=false",
            "--set",
            "resources.enabled=false",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at least one of", result.stderr)

    def test_namespace_is_never_rendered(self):
        """Namespace/kserve belongs to the kubeflow-namespaces chart."""
        self.assertEqual([m for m in self.manifests if m["kind"] == "Namespace"], [])

    def test_every_namespaced_resource_declares_the_owned_namespace(self):
        namespaces = {
            manifest["metadata"].get("namespace")
            for manifest in self.manifests
            if manifest["metadata"].get("namespace")
        }

        self.assertEqual(namespaces, {OWNED_NAMESPACE})

    def test_intentional_omissions_stay_omitted(self):
        """The restricted Pod Security decisions of the Kustomize component."""
        identities = {(m["kind"], m["metadata"]["name"]) for m in self.manifests}

        self.assertNotIn(("DaemonSet", "kserve-localmodelnode-agent"), identities)
        self.assertNotIn(
            (
                "ValidatingWebhookConfiguration",
                "llminferenceserviceconfig.serving.kserve.io",
            ),
            identities,
        )
        self.assertNotIn(
            "LLMInferenceServiceConfig", {m["kind"] for m in self.manifests}
        )

    def test_packaged_chart_stays_under_the_release_size_limit(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = subprocess.run(
                [
                    HELM_BINARY,
                    "package",
                    str(CHART_PATH),
                    "--destination",
                    temporary_directory,
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            archives = list(Path(temporary_directory).glob("*.tgz"))

            self.assertEqual(len(archives), 1)
            self.assertLess(archives[0].stat().st_size, PACKAGED_CHART_SIZE_LIMIT)

    def test_readme_documents_the_two_revision_installation(self):
        readme = (CHART_PATH / "README.md").read_text()

        self.assertIn("--set resources.enabled=false", readme)
        self.assertIn("condition=Established", readme)


if __name__ == "__main__":
    unittest.main()
