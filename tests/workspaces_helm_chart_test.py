#!/usr/bin/env python3
"""Behaviour of the Kubeflow Workspaces Helm chart."""

import shutil
import subprocess
import tempfile
import unittest

from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHART_PATH = REPOSITORY_ROOT / "applications/workspaces/helm"
DEFINITIONS_PAYLOAD = "manifests/platform-crds.yaml"
RESOURCES_PAYLOAD = "manifests/platform-resources.yaml"
RELEASE_NAMESPACE = "kubeflow"
OWNED_NAMESPACE = "kubeflow-workspaces"
OWNED_NAMESPACE_LABELS = {
    "app.kubernetes.io/part-of": "kubeflow-workspaces",
    "istio-injection": "enabled",
    "pod-security.kubernetes.io/enforce": "restricted",
}
DEFINITION_NAMES = {"workspacekinds.kubeflow.org", "workspaces.kubeflow.org"}
AGGREGATED_ROLE_NAMES = [
    "kubeflow-workspaces-admin",
    "kubeflow-workspaces-edit",
    "kubeflow-workspaces-view",
]
AGGREGATION_LABEL_PREFIX = "rbac.authorization.kubeflow.org/aggregate-to-"
CLUSTER_SCOPED_KINDS = {
    "ClusterRole",
    "ClusterRoleBinding",
    "CustomResourceDefinition",
    "Namespace",
    "ValidatingWebhookConfiguration",
}


def render_chart(chart_directory=CHART_PATH, *arguments, namespace=RELEASE_NAMESPACE):
    return subprocess.run(
        [
            "helm",
            "template",
            "kubeflow-workspaces",
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


class WorkspacesHelmChartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = render_chart()
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.rendered = result.stdout
        cls.manifests = load_manifests(result.stdout)

    def test_chart_refuses_a_foreign_release_namespace(self):
        """The release record lives in kubeflow, not in the namespace the chart
        renders, so even kubeflow-workspaces is refused as a release namespace."""
        for namespace in ["not-kubeflow", OWNED_NAMESPACE, "default"]:
            with self.subTest(namespace=namespace):
                result = render_chart(CHART_PATH, namespace=namespace)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "must be installed into the kubeflow namespace", result.stderr
                )

    def test_chart_refuses_an_unsupported_scenario(self):
        for scenario in ["platform", ""]:
            with self.subTest(scenario=scenario):
                result = render_chart(CHART_PATH, "--set", f"scenario={scenario}")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("supported values: istio", result.stderr)

    def test_upstream_template_delimiters_are_not_evaluated(self):
        """The payload is data, not chart code.

        The WorkspaceKind definition documents expressions such as
        {{ httpPathPrefix 'jupyterlab' }}. Rendering the payload through the
        template engine would fail on that unknown function, or silently resolve
        another expression to the empty string.
        """
        payload = (CHART_PATH / DEFINITIONS_PAYLOAD).read_text()
        delimiter_lines = [line for line in payload.splitlines() if "{{" in line]

        self.assertTrue(delimiter_lines, "the payload no longer has a delimiter")
        for line in delimiter_lines:
            self.assertIn(line, self.rendered)

        with tempfile.TemporaryDirectory() as temporary_directory:
            chart_directory = Path(temporary_directory) / "chart"
            shutil.copytree(CHART_PATH, chart_directory)
            with (chart_directory / RESOURCES_PAYLOAD).open("a") as stream:
                stream.write(
                    "---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n"
                    "  name: literal-template-expression\n"
                    f"  namespace: {OWNED_NAMESPACE}\n"
                    "data:\n"
                    '  template: "{{ .Values.workspaceName }}-workspace"\n'
                )

            result = render_chart(chart_directory)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                'template: "{{ .Values.workspaceName }}-workspace"', result.stdout
            )

    def test_missing_or_empty_payload_fails_the_render(self):
        for payload_path in [DEFINITIONS_PAYLOAD, RESOURCES_PAYLOAD]:
            for state in ["missing", "empty", "comments"]:
                with self.subTest(payload=payload_path, state=state):
                    with tempfile.TemporaryDirectory() as temporary_directory:
                        chart_directory = Path(temporary_directory) / "chart"
                        shutil.copytree(CHART_PATH, chart_directory)
                        payload = chart_directory / payload_path
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
        self.assertEqual(
            {definition["metadata"]["name"] for definition in definitions},
            DEFINITION_NAMES,
        )
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
            [
                manifest
                for manifest in remaining
                if manifest["kind"] == "CustomResourceDefinition"
            ],
            [],
        )
        self.assertEqual(len(remaining), len(self.manifests) - len(DEFINITION_NAMES))

    def test_definitions_declare_no_conversion_webhook(self):
        """The README states that this version has no conversion webhook, so a
        synchronization that introduces one must fail here first."""
        for manifest in self.manifests:
            if manifest["kind"] == "CustomResourceDefinition":
                self.assertNotIn("conversion", manifest["spec"])

    def test_aggregated_cluster_roles_leave_rules_to_the_aggregation_controller(self):
        """The aggregation controller owns the rules of a ClusterRole that has
        an aggregationRule. A chart that declares the field, even as an empty
        list, conflicts with that controller on helm upgrade."""
        aggregated_roles = {
            manifest["metadata"]["name"]: manifest
            for manifest in self.manifests
            if manifest["kind"] == "ClusterRole" and "aggregationRule" in manifest
        }

        for name, role in aggregated_roles.items():
            with self.subTest(role=name):
                self.assertNotIn("rules", role)
        for name in AGGREGATED_ROLE_NAMES:
            with self.subTest(role=name):
                self.assertIn(name, aggregated_roles)
                self.assertEqual(
                    aggregated_roles[name]["aggregationRule"],
                    {
                        "clusterRoleSelectors": [
                            {"matchLabels": {AGGREGATION_LABEL_PREFIX + name: "true"}}
                        ]
                    },
                )

    def test_chart_renders_exactly_one_namespace_with_the_baseline_labels(self):
        namespaces = [
            manifest for manifest in self.manifests if manifest["kind"] == "Namespace"
        ]

        self.assertEqual(len(namespaces), 1)
        metadata = namespaces[0]["metadata"]
        self.assertEqual(metadata["name"], OWNED_NAMESPACE)
        for label, value in OWNED_NAMESPACE_LABELS.items():
            self.assertEqual(metadata["labels"].get(label), value)
        # Deleting the namespace on uninstall is part of the chart's contract.
        self.assertNotIn("helm.sh/resource-policy", metadata.get("annotations") or {})

    def test_every_namespaced_resource_declares_the_owned_namespace(self):
        """Nothing may fall back to the release namespace, which is kubeflow."""
        for manifest in self.manifests:
            identity = f'{manifest["kind"]}/{manifest["metadata"]["name"]}'
            with self.subTest(resource=identity):
                if manifest["kind"] in CLUSTER_SCOPED_KINDS:
                    self.assertNotIn("namespace", manifest["metadata"])
                else:
                    self.assertEqual(
                        manifest["metadata"].get("namespace"), OWNED_NAMESPACE
                    )


if __name__ == "__main__":
    unittest.main()
