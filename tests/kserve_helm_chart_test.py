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
PAYLOAD_CHART = "charts/kserve-payload"
RESOURCES_PAYLOAD = f"{PAYLOAD_CHART}/manifests/platform-resources.yaml"
DEFINITIONS_DIRECTORY = f"{PAYLOAD_CHART}/manifests/custom-resource-definitions"
OBSOLETE_TOP_LEVEL_VALUES = {
    "scenario": "scenario=platform",
    "customResourceDefinitions": "customResourceDefinitions.enabled=true",
    "resources": "resources.enabled=false",
}
HELM_COMMAND_SOURCES = (
    CHART_PATH / "README.md",
    REPOSITORY_ROOT / "tests/kserve_helm_install.sh",
    REPOSITORY_ROOT / "tests/helm_lifecycle_test.sh",
)
OWNED_NAMESPACE = "kserve"
CUSTOM_RESOURCE_DEFINITION_COUNT = 20
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


def helm_commands(text):
    """Return every Helm command of a script or a document, continuations joined."""
    return [
        command
        for command in (line.strip() for line in text.replace("\\\n", " ").splitlines())
        if command.startswith("helm ")
    ]


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

    def test_obsolete_top_level_values_are_rejected_with_their_replacement(self):
        """Helm would ignore them silently; the payload chart never sees them."""
        for key, assignment in OBSOLETE_TOP_LEVEL_VALUES.items():
            with self.subTest(key=key):
                result = render_chart(CHART_PATH, "--set", assignment)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f'top-level value "{key}"', result.stderr)
                self.assertIn(f"set payload.{key} instead", result.stderr)

    def test_the_payload_is_an_unpacked_dependency_without_lock_or_archive(self):
        """The release record embeds the parent's files, not the dependency's,
        and the source tree needs no dependency build."""
        parent = yaml.safe_load((CHART_PATH / "Chart.yaml").read_text())
        child = yaml.safe_load((CHART_PATH / PAYLOAD_CHART / "Chart.yaml").read_text())

        self.assertEqual(
            parent["dependencies"],
            [{"name": child["name"], "version": child["version"], "alias": "payload"}],
        )
        self.assertEqual(parent["appVersion"], child["appVersion"])
        self.assertFalse((CHART_PATH / "Chart.lock").exists())
        self.assertEqual(
            sorted(path.name for path in (CHART_PATH / "charts").iterdir()),
            ["kserve-payload"],
        )
        self.assertFalse((CHART_PATH / "manifests").exists())

    def test_an_invalid_scenario_fails(self):
        result = render_chart(CHART_PATH, "--set", "payload.scenario=unknown")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid scenario "unknown"', result.stderr)

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

    def test_missing_definition_payloads_fail_the_render(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            chart_directory = Path(temporary_directory) / "chart"
            shutil.copytree(CHART_PATH, chart_directory)
            shutil.rmtree(chart_directory / DEFINITIONS_DIRECTORY)

            result = render_chart(chart_directory)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no generated custom resource definition", result.stderr)

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
            CHART_PATH, "--set", "payload.customResourceDefinitions.enabled=false"
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
        self.assertEqual(
            len(remaining), len(self.manifests) - CUSTOM_RESOURCE_DEFINITION_COUNT
        )

    def test_first_revision_renders_only_custom_resource_definitions(self):
        result = render_chart(CHART_PATH, "--set", "payload.resources.enabled=false")
        self.assertEqual(result.returncode, 0, result.stderr)

        kinds = {manifest["kind"] for manifest in load_manifests(result.stdout)}

        self.assertEqual(kinds, {"CustomResourceDefinition"})

    def test_second_revision_leaves_out_only_the_cluster_serving_runtimes(self):
        """Their validating webhook fails closed until the controller is ready."""
        result = render_chart(
            CHART_PATH, "--set", "payload.clusterServingRuntimes.enabled=false"
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        second_revision = load_manifests(result.stdout)
        cluster_serving_runtimes = [
            manifest
            for manifest in self.manifests
            if manifest["kind"] == "ClusterServingRuntime"
        ]

        self.assertTrue(cluster_serving_runtimes)
        self.assertEqual(
            second_revision,
            [
                manifest
                for manifest in self.manifests
                if manifest["kind"] != "ClusterServingRuntime"
            ],
        )

    def test_disabling_everything_fails(self):
        result = render_chart(
            CHART_PATH,
            "--set",
            "payload.customResourceDefinitions.enabled=false",
            "--set",
            "payload.resources.enabled=false",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("at least one of", result.stderr)

    def test_namespace_is_never_rendered(self):
        """Namespace/kserve belongs to the kubeflow-namespaces chart."""
        self.assertEqual(
            [
                manifest
                for manifest in self.manifests
                if manifest["kind"] == "Namespace"
            ],
            [],
        )

    def test_every_namespaced_resource_declares_the_owned_namespace(self):
        namespaces = {
            manifest["metadata"].get("namespace")
            for manifest in self.manifests
            if manifest["metadata"].get("namespace")
        }

        self.assertEqual(namespaces, {OWNED_NAMESPACE})

    def test_intentional_omissions_stay_omitted(self):
        """The restricted Pod Security decisions of the Kustomize component."""
        identities = {
            (manifest["kind"], manifest["metadata"]["name"])
            for manifest in self.manifests
        }

        self.assertNotIn(("DaemonSet", "kserve-localmodelnode-agent"), identities)
        self.assertNotIn(
            (
                "ValidatingWebhookConfiguration",
                "llminferenceserviceconfig.serving.kserve.io",
            ),
            identities,
        )
        self.assertNotIn(
            "LLMInferenceServiceConfig",
            {manifest["kind"] for manifest in self.manifests},
        )

    def test_readme_documents_the_three_revision_installation(self):
        readme = (CHART_PATH / "README.md").read_text()

        self.assertIn("--set payload.resources.enabled=false", readme)
        self.assertIn("--set payload.clusterServingRuntimes.enabled=false", readme)
        self.assertIn("condition=Established", readme)
        self.assertNotIn("--reuse-values\n", readme)
        self.assertNotIn("--set resources.", readme)

    def test_no_helm_command_passes_force_conflicts(self):
        """The payload states no field that another controller owns, so no
        documented or scripted Helm command needs the release-wide option."""
        for path in HELM_COMMAND_SOURCES:
            commands = helm_commands(path.read_text())
            with self.subTest(path=path.name):
                self.assertTrue(
                    any(command.startswith("helm upgrade ") for command in commands),
                    f"no helm upgrade command found in {path.name}",
                )
                self.assertEqual(
                    [command for command in commands if "--force" in command], []
                )

    def test_the_payload_states_no_rules_for_the_aggregated_cluster_role(self):
        """The role aggregation controller owns the field; a manifest that
        states it, even as an empty list, conflicts on the next upgrade."""
        aggregated_roles = [
            manifest
            for manifest in self.manifests
            if manifest["kind"] == "ClusterRole" and "aggregationRule" in manifest
        ]

        self.assertEqual(
            [role["metadata"]["name"] for role in aggregated_roles],
            ["kubeflow-kserve-admin"],
        )
        self.assertNotIn("rules", aggregated_roles[0])

    def test_readme_explains_why_no_command_forces_conflicts(self):
        readme = " ".join((CHART_PATH / "README.md").read_text().split())

        self.assertIn("passes `--force-conflicts`", readme)
        self.assertIn(
            "https://kubernetes.io/docs/reference/access-authn-authz/rbac/"
            "#aggregated-clusterroles",
            readme,
        )
        self.assertIn(
            "`helm upgrade --dry-run=server` is not conflict evidence", readme
        )
        self.assertIn("reintroduces `rules: []`", readme)
        self.assertIn("leaves the release without a `deployed` revision", readme)

    def test_readme_separates_retention_from_the_objects_the_chart_provides(self):
        readme = " ".join((CHART_PATH / "README.md").read_text().split())

        self.assertIn(
            "deleted, including every bundled `ClusterServingRuntime` and "
            "`ClusterStorageContainer`",
            readme,
        )
        self.assertIn("No inference is promised", readme)
        self.assertIn("it is not a rollback target", readme)


if __name__ == "__main__":
    unittest.main()
