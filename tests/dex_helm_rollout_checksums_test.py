#!/usr/bin/env python3

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
CHART_DIRECTORY = ROOT_DIRECTORY / "common" / "dex" / "helm"
HELM_BINARY = os.environ.get("HELM_BINARY", "helm")
# Real-shaped credentials. The chart rejects the REPLACE_ME placeholders, so
# every render in this file has to supply something valid first.
VALID_OIDC_CLIENT_SECRET = "pUBnBOY80SnXgjibTYM9ZWNzY2xreNGQok"
VALID_STATIC_PASSWORD_HASH = (
    "$2y$12$4K/VkmDd1q1Orb3xAt82zu8gk7Ad6ReFR4LCP9UeYE90NLiN9Df72"
)
CHECKSUM_KEYS = {
    "checksum/config",
    "checksum/oidc-client",
    "checksum/passwords",
}


class DexRolloutChecksumTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helm_plugins = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.helm_plugins.cleanup()

    def render_manifests(self, *values):
        command = [
            HELM_BINARY,
            "template",
            "dex",
            str(CHART_DIRECTORY),
            "--namespace",
            "auth",
        ]
        # The chart refuses to render while the placeholder credentials are in
        # place, so supply real-shaped ones before any test override.
        for value in (
            f"oidcClient.secret={VALID_OIDC_CLIENT_SECRET}",
            f"staticPassword.hash={VALID_STATIC_PASSWORD_HASH}",
        ):
            command.extend(["--set-string", value])
        for value in values:
            command.extend(["--set-string", value])

        environment = os.environ.copy()
        environment["HELM_PLUGINS"] = self.helm_plugins.name
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        return [manifest for manifest in yaml.safe_load_all(result.stdout) if manifest]

    def render_checksums(self, *values):
        manifests = self.render_manifests(*values)
        deployment = next(
            manifest
            for manifest in manifests
            if manifest.get("kind") == "Deployment"
            and manifest.get("metadata", {}).get("name") == "dex"
        )
        return deployment["spec"]["template"]["metadata"].get("annotations", {})

    def render_dex_config(self, *values):
        manifests = self.render_manifests(*values)
        config_map = next(
            manifest
            for manifest in manifests
            if manifest.get("kind") == "ConfigMap"
            and manifest.get("metadata", {}).get("name") == "dex"
        )
        return yaml.safe_load(config_map["data"]["config.yaml"])

    def test_static_username_preserves_string_overrides(self):
        config = self.render_dex_config("config.staticUsername=null")

        self.assertEqual(config["staticPasswords"][0]["username"], "null")

    def test_installation_uses_user_values_instead_of_ci_fixture(self):
        readme = (CHART_DIRECTORY / "README.md").read_text()
        installation_section = readme.split("## Installation", 1)[1].split(
            "## Namespace names",
            1,
        )[0]

        self.assertNotIn("/ci/", installation_section)
        self.assertIn("--values ./dex-values.yaml", installation_section)
        self.assertIn("`oidcClient.secret`", installation_section)
        self.assertIn("`staticPassword.hash`", installation_section)
        self.assertIn("same OAuth client secret", installation_section)

    def test_checksums_are_stable_and_change_only_for_their_startup_input(self):
        baseline = self.render_checksums()

        self.assertEqual(set(baseline), CHECKSUM_KEYS)
        for checksum in baseline.values():
            self.assertRegex(checksum, re.compile(r"^[0-9a-f]{64}$"))

        self.assertEqual(self.render_checksums(), baseline)
        self.assertEqual(
            self.changed_keys(baseline, self.render_checksums("config.logLevel=debug")),
            {"checksum/config"},
        )
        self.assertEqual(
            self.changed_keys(
                baseline,
                self.render_checksums("oidcClient.secret=changed-oidc-secret"),
            ),
            {"checksum/oidc-client"},
        )
        self.assertEqual(
            self.changed_keys(
                baseline,
                # A different bcrypt hash, because the chart now rejects any
                # value that no password could ever match.
                self.render_checksums(
                    "staticPassword.hash="
                    "$2y$12$k0k8DCLYJm6ByQ6nCsWfE.dQdyBTvOZk3.wPxT/RQ6bDlYnJXtxHi"
                ),
            ),
            {"checksum/passwords"},
        )
        self.assertEqual(self.render_checksums("dex.replicas=3"), baseline)

    @staticmethod
    def changed_keys(before, after):
        return {key for key in CHECKSUM_KEYS if before[key] != after[key]}


if __name__ == "__main__":
    unittest.main()
