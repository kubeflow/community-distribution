#!/usr/bin/env python3

import subprocess
import tempfile
import unittest

from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHART_PATH = REPOSITORY_ROOT / "applications/dashboard/helm"
OWNED_NAMESPACE = "kubeflow"


def render_chart(*set_arguments, namespace=OWNED_NAMESPACE, values=None):
    command = [
        "helm",
        "template",
        "kubeflow-dashboard",
        str(CHART_PATH),
        "--namespace",
        namespace,
    ]
    for set_argument in set_arguments:
        command.extend(["--set", set_argument])

    if values is None:
        return subprocess.run(command, capture_output=True, text=True)

    with tempfile.TemporaryDirectory() as temporary_directory:
        values_path = Path(temporary_directory) / "values.yaml"
        values_path.write_text(yaml.safe_dump(values))
        command.extend(["--values", str(values_path)])
        return subprocess.run(command, capture_output=True, text=True)


def load_manifests(rendered):
    return [document for document in yaml.safe_load_all(rendered) if document]


def find_manifest(manifests, kind, name):
    for manifest in manifests:
        if manifest.get("kind") == kind and manifest["metadata"]["name"] == name:
            return manifest
    raise AssertionError(f"{kind}/{name} was not rendered")


class DashboardHelmChartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = render_chart()
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.manifests = load_manifests(result.stdout)

    def test_chart_refuses_a_foreign_namespace(self):
        result = render_chart(namespace="not-kubeflow")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be installed into the kubeflow namespace", result.stderr)

    def test_image_registry_override_reaches_every_container(self):
        result = render_chart("image.registry=registry.example.com/mirror")
        self.assertEqual(result.returncode, 0, result.stderr)

        images = [
            container["image"]
            for manifest in load_manifests(result.stdout)
            if manifest.get("kind") == "Deployment"
            for container in manifest["spec"]["template"]["spec"]["containers"]
        ]

        self.assertEqual(len(images), 4)
        for image in images:
            with self.subTest(image=image):
                self.assertTrue(image.startswith("registry.example.com/mirror/"))

    def test_image_tag_defaults_to_the_chart_application_version(self):
        chart = yaml.safe_load((CHART_PATH / "Chart.yaml").read_text())

        images = [
            container["image"]
            for manifest in self.manifests
            if manifest.get("kind") == "Deployment"
            for container in manifest["spec"]["template"]["spec"]["containers"]
        ]

        for image in images:
            with self.subTest(image=image):
                self.assertTrue(image.endswith(f":{chart['appVersion']}"))

    def test_identity_headers_stay_consistent_across_both_config_maps(self):
        result = render_chart("identity.userIdHeader=x-goog-authenticated-user-email")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifests = load_manifests(result.stdout)

        dashboard_parameters = find_manifest(
            manifests, "ConfigMap", "dashboard-parameters"
        )
        profiles_config = find_manifest(manifests, "ConfigMap", "profiles-config")

        self.assertEqual(
            dashboard_parameters["data"]["USERID_HEADER"],
            "x-goog-authenticated-user-email",
        )
        self.assertEqual(
            profiles_config["data"]["USERID_HEADER"],
            "x-goog-authenticated-user-email",
        )

    def test_configuration_change_rolls_the_consuming_deployment(self):
        baseline = find_manifest(self.manifests, "Deployment", "dashboard")
        baseline_checksum = baseline["spec"]["template"]["metadata"]["annotations"][
            "checksum/config"
        ]

        result = render_chart("centralDashboard.collectMetrics=false")
        self.assertEqual(result.returncode, 0, result.stderr)
        changed = find_manifest(
            load_manifests(result.stdout), "Deployment", "dashboard"
        )

        self.assertNotEqual(
            changed["spec"]["template"]["metadata"]["annotations"]["checksum/config"],
            baseline_checksum,
        )

    def test_boolean_parameters_render_as_configuration_strings(self):
        dashboard_parameters = find_manifest(
            self.manifests, "ConfigMap", "dashboard-parameters"
        )

        self.assertEqual(dashboard_parameters["data"]["COLLECT_METRICS"], "true")
        self.assertEqual(dashboard_parameters["data"]["REGISTRATION_FLOW"], "false")

    def test_documents_are_inherited_and_overridable(self):
        inherited = find_manifest(self.manifests, "ConfigMap", "dashboard-config")
        self.assertIn("menuLinks", inherited["data"]["links"])

        override = '{\n  "DASHBOARD_FORCE_IFRAME": false\n}'
        result = render_chart(values={"centralDashboard": {"settings": override}})
        self.assertEqual(result.returncode, 0, result.stderr)
        overridden = find_manifest(
            load_manifests(result.stdout), "ConfigMap", "dashboard-config"
        )

        self.assertEqual(overridden["data"]["settings"], override)

    def test_non_string_document_override_is_rejected(self):
        """A document is a string. A map would render as Go's map formatting.

        Helm would accept "map[menuLinks:[]]" and the application could not
        parse it, so the chart must refuse rather than write it.
        """
        cases = [
            ("centralDashboard", "links", {"menuLinks": []}),
            ("centralDashboard", "settings", {"DASHBOARD_FORCE_IFRAME": True}),
            ("profileController", "namespaceLabels", {"example.com/enabled": "true"}),
            ("centralDashboard", "links", ["a", "b"]),
            ("centralDashboard", "settings", False),
        ]
        for section, key, value in cases:
            with self.subTest(value=f"{section}.{key}={value!r}"):
                result = render_chart(values={section: {key: value}})

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{section}.{key} must be a string", result.stderr)

    def test_empty_document_override_inherits_the_upstream_default(self):
        result = render_chart(values={"centralDashboard": {"links": ""}})
        self.assertEqual(result.returncode, 0, result.stderr)
        inherited = find_manifest(
            load_manifests(result.stdout), "ConfigMap", "dashboard-config"
        )

        self.assertIn("menuLinks", inherited["data"]["links"])

    def test_custom_resource_definitions_can_be_disabled(self):
        default_crds = [
            m for m in self.manifests if m["kind"] == "CustomResourceDefinition"
        ]
        self.assertEqual(len(default_crds), 2)
        for crd in default_crds:
            self.assertEqual(
                crd["metadata"]["annotations"]["helm.sh/resource-policy"], "keep"
            )

        result = render_chart("customResourceDefinitions.enabled=false")
        self.assertEqual(result.returncode, 0, result.stderr)
        manifests = load_manifests(result.stdout)

        self.assertEqual(
            [m for m in manifests if m["kind"] == "CustomResourceDefinition"], []
        )
        self.assertEqual(len(manifests), len(self.manifests) - 2)

    def test_profile_controller_configuration_change_rolls_its_deployment(self):
        baseline = find_manifest(self.manifests, "Deployment", "profiles-deployment")
        baseline_checksum = baseline["spec"]["template"]["metadata"]["annotations"][
            "checksum/config"
        ]

        result = render_chart("profileController.admin=admin@example.com")
        self.assertEqual(result.returncode, 0, result.stderr)
        changed = find_manifest(
            load_manifests(result.stdout), "Deployment", "profiles-deployment"
        )

        self.assertNotEqual(
            changed["spec"]["template"]["metadata"]["annotations"]["checksum/config"],
            baseline_checksum,
        )


if __name__ == "__main__":
    unittest.main()
