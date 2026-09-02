#!/usr/bin/env python3

import os
import subprocess
import unittest

from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHART_DIRECTORY = REPOSITORY_ROOT / "applications/pipeline/helm"
HELM_BINARY = os.environ.get("HELM_BINARY", "helm")


def render_chart(*additional_arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["HELM_PLUGINS"] = str(REPOSITORY_ROOT / ".nonexistent-helm-plugins")
    return subprocess.run(
        [
            HELM_BINARY,
            "template",
            "kubeflow-pipelines",
            str(CHART_DIRECTORY),
            "--namespace",
            "kubeflow",
            *additional_arguments,
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def load_rendered_resources(rendered_output: str) -> list[dict]:
    return [
        document
        for document in yaml.safe_load_all(rendered_output)
        if isinstance(document, dict)
    ]


class PipelinesHelmChartLifecycleTest(unittest.TestCase):
    def test_readme_waits_for_every_crd_in_the_helm_release(self):
        readme_text = (CHART_DIRECTORY / "README.md").read_text()

        self.assertIn(
            "helm get manifest kubeflow-pipelines --namespace kubeflow",
            readme_text,
        )
        self.assertIn(
            '$0 == "kind: CustomResourceDefinition"',
            readme_text,
        )

    def test_default_render_contains_only_database_scenario_crds(self):
        self.assertTrue(
            CHART_DIRECTORY.is_dir(),
            f"Chart directory does not exist: {CHART_DIRECTORY}",
        )

        result = render_chart()

        self.assertEqual(result.returncode, 0, result.stderr)
        resources = load_rendered_resources(result.stdout)
        self.assertGreater(len(resources), 0)
        self.assertEqual(
            {resource["kind"] for resource in resources},
            {"CustomResourceDefinition"},
        )
        crd_names = {resource["metadata"]["name"] for resource in resources}
        self.assertIn("applications.app.k8s.io", crd_names)
        self.assertNotIn("pipelines.pipelines.kubeflow.org", crd_names)

    def test_database_values_render_complete_database_scenario(self):
        result = render_chart(
            "--values",
            str(CHART_DIRECTORY / "ci/values-platform-database.yaml"),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        resources = load_rendered_resources(result.stdout)
        resource_identifiers = {
            (
                resource["kind"],
                resource.get("metadata", {}).get("namespace", ""),
                resource["metadata"]["name"],
            )
            for resource in resources
        }
        self.assertIn(
            ("Application", "kubeflow", "kubeflow"),
            resource_identifiers,
        )
        self.assertIn(
            (
                "DecoratorController",
                "kubeflow",
                "kubeflow-pipelines-profile-controller",
            ),
            resource_identifiers,
        )
        self.assertNotIn(
            (
                "Certificate",
                "kubeflow",
                "kfp-api-webhook-cert",
            ),
            resource_identifiers,
        )
        self.assertNotIn(
            (
                "CustomResourceDefinition",
                "",
                "pipelines.pipelines.kubeflow.org",
            ),
            resource_identifiers,
        )

    def test_kubernetes_native_values_render_complete_native_scenario(self):
        result = render_chart(
            "--values",
            str(CHART_DIRECTORY / "ci/values-platform-k8s-native.yaml"),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        resources = load_rendered_resources(result.stdout)
        resource_identifiers = {
            (
                resource["kind"],
                resource.get("metadata", {}).get("namespace", ""),
                resource["metadata"]["name"],
            )
            for resource in resources
        }
        self.assertIn(
            (
                "CustomResourceDefinition",
                "",
                "pipelines.pipelines.kubeflow.org",
            ),
            resource_identifiers,
        )
        self.assertIn(
            (
                "DecoratorController",
                "kubeflow",
                "kubeflow-pipelines-profile-controller",
            ),
            resource_identifiers,
        )
        self.assertIn(
            (
                "Certificate",
                "kubeflow",
                "kfp-api-webhook-cert",
            ),
            resource_identifiers,
        )
        self.assertNotIn(
            (
                "CustomResourceDefinition",
                "",
                "applications.app.k8s.io",
            ),
            resource_identifiers,
        )
        self.assertNotIn(
            ("Application", "kubeflow", "kubeflow"),
            resource_identifiers,
        )

    def test_explicit_empty_scenario_defaults_to_database(self):
        result = render_chart(
            "--set-string",
            "scenario=",
            "--set",
            "install.enabled=true",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        resource_identifiers = {
            (
                resource["kind"],
                resource.get("metadata", {}).get("namespace", ""),
                resource["metadata"]["name"],
            )
            for resource in load_rendered_resources(result.stdout)
        }
        self.assertIn(
            ("Application", "kubeflow", "kubeflow"),
            resource_identifiers,
        )

    def test_invalid_scenario_fails_with_supported_values(self):
        result = render_chart("--set-string", "scenario=unsupported")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "supported values: platform-database, platform-k8s-native",
            result.stderr,
        )

    def test_install_requires_crds(self):
        result = render_chart(
            "--set",
            "crds.enabled=false",
            "--set",
            "install.enabled=true",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "install.enabled=true requires crds.enabled=true",
            result.stderr,
        )

    def test_disabling_crds_and_install_fails(self):
        result = render_chart(
            "--set",
            "crds.enabled=false",
            "--set",
            "install.enabled=false",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "at least one of crds.enabled or install.enabled must be true",
            result.stderr,
        )


if __name__ == "__main__":
    unittest.main()
