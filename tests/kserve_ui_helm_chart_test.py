#!/usr/bin/env python3
"""Behaviour of the distribution Models UI Helm chart."""

import os
import shutil
import subprocess
import tempfile
import unittest

from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHART_PATH = REPOSITORY_ROOT / "applications/kserve/kserve-ui/helm"
RESOURCES_PAYLOAD = "manifests/platform-resources.yaml"
OWNED_NAMESPACE = "kserve"


def render_chart(chart_directory=CHART_PATH, *arguments, namespace=OWNED_NAMESPACE):
    return subprocess.run(
        [
            "helm",
            "template",
            "kserve-models-web-application",
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


class ModelsUiHelmChartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = render_chart()
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        cls.manifests = load_manifests(result.stdout)

    def test_installer_can_run_again_when_the_independent_ui_release_exists(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            helm = directory / "helm"
            helm.write_text(
                "#!/usr/bin/env python3\n"
                "import os, pathlib, sys\n"
                "state = pathlib.Path(os.environ['UI_RELEASE_TEST_STATE'])\n"
                "arguments = sys.argv[1:]\n"
                "if arguments[0] == 'install' and state.exists():\n"
                "    sys.exit('cannot reuse a name that is still in use')\n"
                "assert arguments[0] in ('install', 'upgrade'), arguments\n"
                "if arguments[0] == 'upgrade':\n"
                "    assert '--install' in arguments, arguments\n"
                "    assert '--reset-values' in arguments, arguments\n"
                "state.write_text(str(int(state.read_text()) + 1) if state.exists() else '1')\n"
            )
            helm.chmod(0o755)
            kubectl = directory / "kubectl"
            kubectl.write_text("#!/usr/bin/env bash\nexit 0\n")
            kubectl.chmod(0o755)
            state = directory / "release-state"
            environment = os.environ | {
                "PATH": f"{directory}:{os.environ['PATH']}",
                "UI_RELEASE_TEST_STATE": str(state),
            }
            for _ in range(2):
                result = subprocess.run(
                    ["bash", str(REPOSITORY_ROOT / "tests/kserve_ui_helm_install.sh")],
                    env=environment,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(state.read_text(), "2")

    def test_chart_refuses_a_foreign_namespace(self):
        result = render_chart(CHART_PATH, namespace="not-kserve")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be installed into the kserve namespace", result.stderr)

    def test_upstream_template_delimiters_are_not_evaluated(self):
        """The payload is data, not chart code.

        Rendering it through the template engine would silently resolve an
        upstream expression to the empty string. Embedded content may legitimately include template delimiters.
        """
        with tempfile.TemporaryDirectory() as temporary_directory:
            chart_directory = Path(temporary_directory) / "chart"
            shutil.copytree(CHART_PATH, chart_directory)
            with (chart_directory / RESOURCES_PAYLOAD).open("a") as stream:
                stream.write(
                    "---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n"
                    "  name: literal-template-expression\n  namespace: kserve\n"
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

    def test_default_render_matches_all_source_objects_without_normalization(self):
        baseline = subprocess.run(
            ["kustomize", "build", "applications/kserve/kserve-ui"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        def indexed(resources):
            return {
                (
                    resource["apiVersion"],
                    resource["kind"],
                    resource["metadata"].get("namespace", ""),
                    resource["metadata"]["name"],
                ): resource
                for resource in resources
            }

        expected = indexed(load_manifests(baseline.stdout))
        actual = indexed(self.manifests)
        self.assertEqual(len(self.manifests), 9)
        self.assertEqual(actual, expected)
        self.assertFalse(
            any(
                resource["kind"]
                in ("Namespace", "CustomResourceDefinition", "InferenceService")
                for resource in self.manifests
            )
        )

    def test_application_version_matches_the_default_image_in_both_charts(self):
        experimental_chart = REPOSITORY_ROOT / "experimental/helm/charts/kserve-ui"
        platform_version = yaml.safe_load((CHART_PATH / "Chart.yaml").read_text())[
            "appVersion"
        ]
        experimental_version = yaml.safe_load(
            (experimental_chart / "Chart.yaml").read_text()
        )["appVersion"]
        experimental_values = yaml.safe_load(
            (experimental_chart / "values.yaml").read_text()
        )
        deployment = next(
            resource for resource in self.manifests if resource["kind"] == "Deployment"
        )
        image = deployment["spec"]["template"]["spec"]["containers"][0]["image"]

        self.assertEqual(experimental_version, platform_version)
        self.assertEqual(
            experimental_values["global"]["imageTag"], platform_version.lstrip("v")
        )
        self.assertEqual(
            image, f"ghcr.io/kserve/models-web-app:{platform_version.lstrip('v')}"
        )

    def test_unsupported_legacy_values_fail_instead_of_being_ignored(self):
        result = render_chart(CHART_PATH, "--set", "app.replicas=2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("additional properties", result.stderr.lower())

    def test_unsupported_scenario_fails(self):
        result = render_chart(CHART_PATH, "--set", "scenario=standalone")
        self.assertNotEqual(result.returncode, 0)

    def test_every_resource_declares_the_owned_namespace(self):
        namespaces = {
            manifest["metadata"].get("namespace")
            for manifest in self.manifests
            if manifest["metadata"].get("namespace")
        }

        self.assertEqual(namespaces, {OWNED_NAMESPACE})


if __name__ == "__main__":
    unittest.main()
