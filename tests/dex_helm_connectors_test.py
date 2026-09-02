#!/usr/bin/env python3
"""Cover the Dex connector configuration surface.

Replacing the built-in static password login with a real identity provider must
be a values change. These tests hold that contract, and hold the default output
unchanged so Kustomize parity is unaffected.
"""

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
CHART_DIRECTORY = ROOT_DIRECTORY / "common" / "dex" / "helm"
HELM_BINARY = os.environ.get("HELM_BINARY", "helm")

KEYCLOAK_VALUES = textwrap.dedent("""\
    config:
      enablePasswordDB: false
      connectors:
      - type: oidc
        id: keycloak
        name: Keycloak
        config:
          issuer: https://keycloak.example.com/realms/kubeflow
          clientID: $KEYCLOAK_CLIENT_ID
          clientSecret: $KEYCLOAK_CLIENT_SECRET
          redirectURI: https://kubeflow.example.com/dex/callback
    extraEnvironmentSecrets:
    - keycloak-oidc-credentials
    """)


class DexConnectorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helm_plugins = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.helm_plugins.cleanup()

    def render(self, values_content=None, *arguments):
        command = [
            HELM_BINARY,
            "template",
            "dex",
            str(CHART_DIRECTORY),
            "--namespace",
            "auth",
        ]
        values_file = None
        if values_content is not None:
            values_file = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
            values_file.write(values_content)
            values_file.close()
            command.extend(["--values", values_file.name])
        command.extend(arguments)

        environment = os.environ.copy()
        environment["HELM_PLUGINS"] = self.helm_plugins.name
        try:
            return subprocess.run(
                command, capture_output=True, text=True, env=environment
            )
        finally:
            if values_file is not None:
                os.unlink(values_file.name)

    def manifests(self, rendered_chart):
        return [document for document in yaml.safe_load_all(rendered_chart) if document]

    def dex_configuration(self, rendered_chart):
        config_map = next(
            manifest
            for manifest in self.manifests(rendered_chart)
            if manifest.get("kind") == "ConfigMap"
            and manifest.get("metadata", {}).get("name") == "dex"
        )
        return yaml.safe_load(config_map["data"]["config.yaml"])

    def test_default_configuration_has_no_connectors(self):
        """The default must stay byte-identical to the Kustomize baseline."""
        result = self.render()

        self.assertEqual(result.returncode, 0, result.stderr)
        configuration = self.dex_configuration(result.stdout)
        self.assertNotIn("connectors", configuration)
        self.assertTrue(configuration["enablePasswordDB"])
        self.assertEqual(len(configuration["staticPasswords"]), 1)

    def test_connector_replaces_the_static_password_login(self):
        result = self.render(KEYCLOAK_VALUES)

        self.assertEqual(result.returncode, 0, result.stderr)
        configuration = self.dex_configuration(result.stdout)
        self.assertNotIn("staticPasswords", configuration)
        self.assertFalse(configuration["enablePasswordDB"])
        self.assertEqual([c["id"] for c in configuration["connectors"]], ["keycloak"])

    def test_connector_secrets_stay_environment_references(self):
        """Credentials belong in a Secret, never in the rendered ConfigMap."""
        result = self.render(KEYCLOAK_VALUES)

        self.assertEqual(result.returncode, 0, result.stderr)
        connector = self.dex_configuration(result.stdout)["connectors"][0]
        self.assertEqual(connector["config"]["clientSecret"], "$KEYCLOAK_CLIENT_SECRET")

    def test_extra_environment_secrets_reach_the_container(self):
        result = self.render(KEYCLOAK_VALUES)

        self.assertEqual(result.returncode, 0, result.stderr)
        deployment = next(
            manifest
            for manifest in self.manifests(result.stdout)
            if manifest.get("kind") == "Deployment"
        )
        container = deployment["spec"]["template"]["spec"]["containers"][0]
        referenced = [entry["secretRef"]["name"] for entry in container["envFrom"]]
        self.assertEqual(
            referenced,
            ["dex-oidc-client", "dex-passwords", "keycloak-oidc-credentials"],
        )

    def test_changing_a_connector_restarts_dex(self):
        """The configuration checksum must move, or helm upgrade changes nothing."""
        baseline = self.render(KEYCLOAK_VALUES)
        changed = self.render(
            KEYCLOAK_VALUES.replace("keycloak.example.com", "sso.example.com")
        )

        self.assertEqual(baseline.returncode, 0, baseline.stderr)
        self.assertEqual(changed.returncode, 0, changed.stderr)

        def checksum(rendered_chart):
            deployment = next(
                manifest
                for manifest in self.manifests(rendered_chart)
                if manifest.get("kind") == "Deployment"
            )
            return deployment["spec"]["template"]["metadata"]["annotations"][
                "checksum/config"
            ]

        self.assertNotEqual(checksum(baseline.stdout), checksum(changed.stdout))

    def test_disabling_the_password_database_without_a_connector_fails(self):
        """Otherwise Dex starts with no way to authenticate anyone."""
        result = self.render(None, "--set", "config.enablePasswordDB=false")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no way to authenticate anyone", result.stderr)

    def test_connectors_must_be_a_list(self):
        result = self.render(None, "--set-string", "config.connectors=keycloak")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("config.connectors must be a list", result.stderr)

    def test_connector_must_declare_type_id_and_name(self):
        for missing in ("type", "id", "name"):
            with self.subTest(missing=missing):
                connector = {"type": "oidc", "id": "keycloak", "name": "Keycloak"}
                del connector[missing]
                arguments = []
                for field, value in connector.items():
                    arguments.extend(
                        ["--set-string", f"config.connectors[0].{field}={value}"]
                    )
                result = self.render(None, *arguments)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f'missing the required field "{missing}"', result.stderr)

    def test_extra_environment_secrets_must_be_a_list(self):
        result = self.render(None, "--set-string", "extraEnvironmentSecrets=secret")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("extraEnvironmentSecrets must be a list", result.stderr)

    def test_certificate_authority_secret_is_mounted_read_only(self):
        """A private authority needs a file; rootCAs cannot read a Secret."""
        values = KEYCLOAK_VALUES + (
            "connectorCertificateAuthoritySecret: corporate-certificate-authority\n"
        )
        result = self.render(values)

        self.assertEqual(result.returncode, 0, result.stderr)
        deployment = next(
            manifest
            for manifest in self.manifests(result.stdout)
            if manifest.get("kind") == "Deployment"
        )
        pod = deployment["spec"]["template"]["spec"]
        mount = next(
            m
            for m in pod["containers"][0]["volumeMounts"]
            if m["mountPath"] == "/etc/dex/certificate-authorities"
        )
        self.assertTrue(mount["readOnly"])
        volume = next(
            v
            for v in pod["volumes"]
            if v["name"] == "connector-certificate-authorities"
        )
        self.assertEqual(
            volume["secret"]["secretName"], "corporate-certificate-authority"
        )

    def test_no_certificate_authority_volume_by_default(self):
        result = self.render(KEYCLOAK_VALUES)

        self.assertEqual(result.returncode, 0, result.stderr)
        deployment = next(
            manifest
            for manifest in self.manifests(result.stdout)
            if manifest.get("kind") == "Deployment"
        )
        volumes = [v["name"] for v in deployment["spec"]["template"]["spec"]["volumes"]]
        self.assertEqual(volumes, ["config"])

    def test_root_ca_path_without_the_secret_fails(self):
        """Otherwise Dex starts and cannot read the certificate it was told to."""
        marker = "      redirectURI: https://kubeflow.example.com/dex/callback\n"
        self.assertIn(marker, KEYCLOAK_VALUES, "test fixture drifted")
        values = KEYCLOAK_VALUES.replace(
            marker,
            marker
            + "      rootCAs:\n"
            + "      - /etc/dex/certificate-authorities/ca.crt\n",
        )
        result = self.render(values)

        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("connectorCertificateAuthoritySecret is not set", result.stderr)

    def test_connector_fields_must_be_non_empty_strings(self):
        """Presence is not enough: Dex cannot use type: 1 or an empty id."""
        base = [
            "--set",
            "config.enablePasswordDB=false",
            "--set-string",
            "config.connectors[0].name=Keycloak",
        ]
        wrong_type = self.render(
            None,
            *base,
            "--set-string",
            "config.connectors[0].id=keycloak",
            "--set",
            "config.connectors[0].type=1",
        )
        self.assertNotEqual(wrong_type.returncode, 0)
        self.assertIn("must be a string", wrong_type.stderr)

        empty = self.render(
            None,
            *base,
            "--set-string",
            "config.connectors[0].type=oidc",
            "--set-string",
            "config.connectors[0].id=",
        )
        self.assertNotEqual(empty.returncode, 0)
        self.assertIn("is empty", empty.stderr)

    def test_extra_environment_secret_entries_must_be_names(self):
        result = self.render(None, "--set", "extraEnvironmentSecrets[0]=1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be a Secret name", result.stderr)

    def test_secret_names_are_quoted(self):
        """An unquoted numeric-looking name renders as a YAML number."""
        values = KEYCLOAK_VALUES.replace("- keycloak-oidc-credentials", '- "012345"')
        result = self.render(values)

        self.assertEqual(result.returncode, 0, result.stderr)
        deployment = next(
            manifest
            for manifest in self.manifests(result.stdout)
            if manifest.get("kind") == "Deployment"
        )
        names = [
            entry["secretRef"]["name"]
            for entry in deployment["spec"]["template"]["spec"]["containers"][0][
                "envFrom"
            ]
        ]
        self.assertIn("012345", names)

    def test_paths_that_resolve_into_the_mount_are_caught(self):
        """Repeated separators resolve to the same file on Linux."""
        marker = "      redirectURI: https://kubeflow.example.com/dex/callback\n"
        for path in (
            "/etc/dex/certificate-authorities/ca.crt",
            "/etc/dex//certificate-authorities/ca.crt",
            "//etc/dex/certificate-authorities/ca.crt",
        ):
            with self.subTest(path=path):
                values = KEYCLOAK_VALUES.replace(
                    marker, marker + "      rootCAs:\n" + f"      - {path}\n"
                )
                result = self.render(values)

                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn(
                    "connectorCertificateAuthoritySecret is not set", result.stderr
                )

    def test_a_sibling_directory_is_not_treated_as_the_mount(self):
        """hasPrefix alone would match /etc/dex/certificate-authorities-elsewhere."""
        marker = "      redirectURI: https://kubeflow.example.com/dex/callback\n"
        values = KEYCLOAK_VALUES.replace(
            marker,
            marker
            + "      rootCAs:\n"
            + "      - /etc/dex/certificate-authorities-elsewhere/ca.crt\n",
        )
        result = self.render(values)

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_non_normalized_root_ca_path_is_rejected(self):
        """/etc/dex/./certificate-authorities resolves into the mount."""
        marker = "      redirectURI: https://kubeflow.example.com/dex/callback\n"
        values = KEYCLOAK_VALUES.replace(
            marker,
            marker
            + "      rootCAs:\n"
            + "      - /etc/dex/./certificate-authorities/ca.crt\n",
        )
        result = self.render(values)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a normalized path", result.stderr)

    def test_disabled_dex_does_not_validate_unused_values(self):
        result = self.render(
            None, "--set", "dex.enabled=false", "--set", "config.enablePasswordDB=false"
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
