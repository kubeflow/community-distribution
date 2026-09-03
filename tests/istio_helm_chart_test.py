#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest

from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CHART_DIRECTORY = REPOSITORY_ROOT / "common/istio/helm"
OAUTH2_PROXY_VALUES = CHART_DIRECTORY / "ci/values-oauth2-proxy.yaml"
GKE_VALUES = CHART_DIRECTORY / "ci/values-gke.yaml"
# Both payloads embed the oauth2-proxy extension provider, so both take the
# substitution path in kubeflow-istio.renderFile.
SUBSTITUTED_PROFILE_VALUES = (OAUTH2_PROXY_VALUES, GKE_VALUES)
SYNCHRONIZATION_SCRIPT = REPOSITORY_ROOT / "scripts/synchronize-istio-manifests.sh"
HELM_BINARY = os.environ.get("HELM_BINARY", "helm")


class IstioHelmChartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helm_plugins = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.helm_plugins.cleanup()

    def render_chart(self, *arguments, values=OAUTH2_PROXY_VALUES):
        environment = os.environ.copy()
        environment["HELM_PLUGINS"] = self.helm_plugins.name
        return subprocess.run(
            [
                HELM_BINARY,
                "template",
                "istio",
                str(CHART_DIRECTORY),
                "--namespace",
                "istio-system",
                "--values",
                str(values),
                *arguments,
            ],
            capture_output=True,
            text=True,
            env=environment,
        )

    def oauth2_proxy_provider(self, rendered_chart):
        manifests = [
            manifest for manifest in yaml.safe_load_all(rendered_chart) if manifest
        ]
        istio_config_map = next(
            manifest
            for manifest in manifests
            if manifest.get("kind") == "ConfigMap"
            and manifest.get("metadata", {}).get("name") == "istio"
            and manifest.get("metadata", {}).get("namespace") == "istio-system"
        )
        mesh_configuration = yaml.safe_load(istio_config_map["data"]["mesh"])
        return next(
            provider["envoyExtAuthzHttp"]
            for provider in mesh_configuration["extensionProviders"]
            if provider.get("name") == "oauth2-proxy"
        )

    def test_custom_oauth2_proxy_service_and_port_are_rendered(self):
        for values in SUBSTITUTED_PROFILE_VALUES:
            with self.subTest(values=values.name):
                result = self.render_chart(
                    "--set-string",
                    "oauth2Proxy.service=custom-auth.oauth2-proxy.svc.cluster.local",
                    "--set-string",
                    "oauth2Proxy.port=18443",
                    values=values,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                provider = self.oauth2_proxy_provider(result.stdout)
                self.assertEqual(
                    provider["service"],
                    "custom-auth.oauth2-proxy.svc.cluster.local",
                )
                self.assertEqual(provider["port"], 18443)

    def test_supported_oauth2_proxy_service_names_are_rendered(self):
        supported_service_names = [
            "oauth2-proxy",
            "oauth2-proxy.oauth2-proxy",
            "oauth2-proxy.oauth2-proxy.svc.cluster.local",
        ]

        for service_name in supported_service_names:
            with self.subTest(service_name=service_name):
                result = self.render_chart(
                    "--set-string",
                    f"oauth2Proxy.service={service_name}",
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    self.oauth2_proxy_provider(result.stdout)["service"],
                    service_name,
                )

    def test_invalid_oauth2_proxy_service_names_fail_before_rendering(self):
        invalid_service_names = [
            "",
            "bad: value",
            "OAuth2-proxy",
            "oauth2_proxy",
            ".oauth2-proxy",
            "oauth2-proxy.",
            "-oauth2-proxy",
            "oauth2-proxy-",
            "a" * 64,
            "a" * 254,
        ]

        for service_name in invalid_service_names:
            with self.subTest(service_name=service_name):
                result = self.render_chart(
                    "--set-string",
                    f"oauth2Proxy.service={service_name}",
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "oauth2Proxy.service must be a valid DNS-1123 service name",
                    result.stderr,
                )

    def test_port_range_boundaries_accept_integer_typed_values(self):
        for port in [1, 65535]:
            with self.subTest(port=port):
                result = self.render_chart(
                    "--set",
                    f"oauth2Proxy.port={port}",
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    self.oauth2_proxy_provider(result.stdout)["port"],
                    port,
                )

    def test_invalid_oauth2_proxy_ports_fail_before_rendering(self):
        invalid_ports = ["not-a-port", "0", "65536"]

        for port in invalid_ports:
            with self.subTest(port=port):
                result = self.render_chart(
                    "--set-string",
                    f"oauth2Proxy.port={port}",
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    "oauth2Proxy.port must be a decimal integer between 1 and 65535",
                    result.stderr,
                )

    def test_unsupported_profile_fails_before_rendering(self):
        result = self.render_chart("--set-string", "profile=unsupported")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            'unsupported istio profile "unsupported"',
            result.stderr,
        )

    def test_readme_uses_canonical_synchronization_script_for_regeneration(self):
        readme = (CHART_DIRECTORY / "README.md").read_text()
        regeneration_section = readme.split("## Regenerate Static Manifests", 1)[
            1
        ].split("## Comparison", 1)[0]

        self.assertIn("scripts/synchronize-istio-manifests.sh", regeneration_section)
        self.assertNotIn("kustomize build", regeneration_section)

    def test_synchronization_uses_shared_atomic_helpers(self):
        synchronization_script = SYNCHRONIZATION_SCRIPT.read_text()

        self.assertIn(
            "update_helm_chart_application_version \\\n  "
            '"$ISTIO_DIRECTORY/helm/Chart.yaml" "$COMMIT"',
            synchronization_script,
        )
        self.assertIn("write_generated_file_atomically", synchronization_script)
        self.assertIn(
            '! -path "$ISTIO_DIRECTORY/helm/Chart.yaml"',
            synchronization_script,
        )
        self.assertNotIn('sed -i "s|^appVersion:', synchronization_script)
        self.assertNotIn(
            '> "$HELM_MANIFESTS_DIRECTORY/networkpolicies.yaml"',
            synchronization_script,
        )

    def test_manifests_use_supported_image_registry(self):
        istio_directory = REPOSITORY_ROOT / "common/istio"
        manifests = "\n".join(
            manifest.read_text() for manifest in istio_directory.rglob("*.yaml")
        )

        self.assertNotIn("registry.istio.io/release", manifests)
        for image in ["install-cni", "pilot", "proxyv2", "ztunnel"]:
            self.assertIn(f"docker.io/istio/{image}:1.31.0", manifests)


if __name__ == "__main__":
    unittest.main()
