#!/usr/bin/env python3

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
CHART_DIRECTORY = ROOT_DIRECTORY / "applications" / "spark" / "spark-operator" / "helm"
SYNCHRONIZATION_SCRIPT = (
    ROOT_DIRECTORY / "scripts" / "synchronize-spark-operator-manifests.sh"
)
HELM_BINARY = os.environ.get("HELM_BINARY", "helm")
CHART_REPOSITORY = "https://kubeflow.github.io/spark-operator"

# The upstream chart derives resource names and spec.selector.matchLabels from
# .Release.Name, and the Kustomize baseline was rendered with this one.
RELEASE_NAME = "spark-operator"
OWNED_NAMESPACE = "kubeflow"
SIDECAR_INJECTION_LABEL = "sidecar.istio.io/inject"
AGGREGATED_ROLES = {
    "kubeflow-spark-admin",
    "kubeflow-spark-edit",
    "kubeflow-spark-view",
}


class SparkOperatorHelmChartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helm_plugins = tempfile.TemporaryDirectory()
        cls.environment = os.environ.copy()
        cls.environment["HELM_PLUGINS"] = cls.helm_plugins.name

        subprocess.run(
            [HELM_BINARY, "repo", "add", "spark-operator", CHART_REPOSITORY],
            capture_output=True,
            text=True,
            env=cls.environment,
        )
        dependencies = subprocess.run(
            [HELM_BINARY, "dependency", "build", str(CHART_DIRECTORY)],
            capture_output=True,
            text=True,
            env=cls.environment,
        )
        if dependencies.returncode != 0:
            raise unittest.SkipTest(
                f"chart dependency is unavailable: {dependencies.stderr}"
            )

        cls.manifests = cls.render(namespace=OWNED_NAMESPACE)

    @classmethod
    def tearDownClass(cls):
        cls.helm_plugins.cleanup()

    @classmethod
    def render(cls, *values, namespace=OWNED_NAMESPACE):
        command = [
            HELM_BINARY,
            "template",
            RELEASE_NAME,
            str(CHART_DIRECTORY),
            "--namespace",
            namespace,
            "--include-crds",
        ]
        for value in values:
            command.extend(["--set", value])

        result = subprocess.run(
            command, capture_output=True, text=True, env=cls.environment
        )
        if result.returncode != 0:
            raise AssertionError(f"helm template failed: {result.stderr}")
        return [manifest for manifest in yaml.safe_load_all(result.stdout) if manifest]

    def find_manifest(self, manifests, kind, name):
        for manifest in manifests:
            if (
                manifest.get("kind") == kind
                and manifest.get("metadata", {}).get("name") == name
            ):
                return manifest
        raise AssertionError(f"{kind}/{name} was not rendered")

    def test_chart_refuses_a_foreign_namespace(self):
        command = [
            HELM_BINARY,
            "template",
            RELEASE_NAME,
            str(CHART_DIRECTORY),
            "--namespace",
            "not-kubeflow",
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, env=self.environment
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be installed into the kubeflow namespace", result.stderr)

    def test_sidecar_injection_is_disabled_on_the_pod_template_only(self):
        """The Kustomize patches target spec.template.metadata.labels.

        Upstream places controller.labels and webhook.labels in the pod
        template. If a release ever moved them to the Deployment, the pods would
        silently rejoin the mesh while the rendered manifest still looked
        configured.
        """
        for name in ("spark-operator-controller", "spark-operator-webhook"):
            with self.subTest(deployment=name):
                deployment = self.find_manifest(self.manifests, "Deployment", name)

                pod_labels = deployment["spec"]["template"]["metadata"]["labels"]
                self.assertEqual(pod_labels.get(SIDECAR_INJECTION_LABEL), "false")

                deployment_labels = deployment["metadata"].get("labels", {})
                self.assertNotIn(SIDECAR_INJECTION_LABEL, deployment_labels)

    def test_job_namespaces_selects_every_namespace(self):
        """[""] renders --namespaces="", an empty list renders no argument.

        The synchronization script passes --set "spark.jobNamespaces={}", which
        Helm parses as a list holding the empty string, so the baseline carries
        the argument.
        """
        for name in ("spark-operator-controller", "spark-operator-webhook"):
            with self.subTest(deployment=name):
                deployment = self.find_manifest(self.manifests, "Deployment", name)
                arguments = deployment["spec"]["template"]["spec"]["containers"][0][
                    "args"
                ]
                self.assertIn('--namespaces=""', arguments)

    def test_aggregated_roles_can_be_disabled(self):
        rendered = {
            manifest["metadata"]["name"]
            for manifest in self.manifests
            if manifest.get("kind") == "ClusterRole"
        }
        self.assertTrue(AGGREGATED_ROLES.issubset(rendered))

        without_roles = self.render("kubeflow.aggregatedRoles.enabled=false")
        remaining = {
            manifest["metadata"]["name"]
            for manifest in without_roles
            if manifest.get("kind") == "ClusterRole"
        }

        self.assertEqual(remaining & AGGREGATED_ROLES, set())
        self.assertEqual(
            len(self.manifests) - len(without_roles), len(AGGREGATED_ROLES)
        )

    def test_dependency_version_matches_the_synchronized_upstream_commit(self):
        """The one maintenance hazard a wrapper introduces, made into a test."""
        script = SYNCHRONIZATION_SCRIPT.read_text()
        commit = re.search(r'^COMMIT="v?([^"]+)"', script, re.MULTILINE)
        self.assertIsNotNone(commit, "COMMIT is not declared in the script")

        chart = yaml.safe_load((CHART_DIRECTORY / "Chart.yaml").read_text())
        dependency = next(
            entry
            for entry in chart["dependencies"]
            if entry["name"] == "spark-operator"
        )

        self.assertEqual(dependency["version"], commit.group(1))
        self.assertEqual(str(chart["appVersion"]), commit.group(1))

    def test_dependency_version_is_pinned_exactly(self):
        """A range would let two installations render differently."""
        chart = yaml.safe_load((CHART_DIRECTORY / "Chart.yaml").read_text())
        dependency = next(
            entry
            for entry in chart["dependencies"]
            if entry["name"] == "spark-operator"
        )

        self.assertRegex(dependency["version"], r"^\d+\.\d+\.\d+")

    def test_chart_carries_no_crds_directory(self):
        """The dependency owns the definitions; a second copy would collide.

        Resources installed from a subchart crds directory carry no Helm
        ownership metadata, so declaring the same ones here would fail the
        ownership check on install.
        """
        self.assertFalse((CHART_DIRECTORY / "crds").exists())


if __name__ == "__main__":
    unittest.main()
