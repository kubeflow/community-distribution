#!/usr/bin/env python3
"""Cover the credential guards in the dex and oauth2-proxy charts.

The charts ship REPLACE_ME defaults. Installing with them produced a Secret
holding a publicly known OIDC client secret, and for oauth2-proxy a publicly
known cookie secret, which signs session cookies.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
DEX_CHART = ROOT_DIRECTORY / "common" / "dex" / "helm"
OAUTH2_PROXY_CHART = ROOT_DIRECTORY / "common" / "oauth2-proxy" / "helm"
HELM_BINARY = os.environ.get("HELM_BINARY", "helm")

VALID_BCRYPT_HASH = "$2y$12$4K/VkmDd1q1Orb3xAt82zu8gk7Ad6ReFR4LCP9UeYE90NLiN9Df72"


class CredentialGuardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.helm_plugins = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.helm_plugins.cleanup()

    def render(self, chart, namespace, *values, booleans=()):
        command = [
            HELM_BINARY,
            "template",
            "release",
            str(chart),
            "--namespace",
            namespace,
        ]
        for value in values:
            command.extend(["--set-string", value])
        # --set-string would make "false" a non-empty, truthy string.
        for value in booleans:
            command.extend(["--set", value])

        environment = os.environ.copy()
        environment["HELM_PLUGINS"] = self.helm_plugins.name
        return subprocess.run(command, capture_output=True, text=True, env=environment)

    def render_dex(self, *values, booleans=()):
        return self.render(DEX_CHART, "auth", *values, booleans=booleans)

    def render_oauth2_proxy(self, *values, booleans=()):
        return self.render(
            OAUTH2_PROXY_CHART, "oauth2-proxy", *values, booleans=booleans
        )

    def test_dex_defaults_are_rejected(self):
        result = self.render_dex()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("oidcClient.secret is still the placeholder", result.stderr)

    def test_oauth2_proxy_defaults_are_rejected(self):
        result = self.render_oauth2_proxy()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "credentials.clientSecret is still the placeholder", result.stderr
        )

    def test_disabled_workloads_do_not_need_credentials(self):
        """No Secret is rendered, so the placeholders are unused."""
        dex = self.render_dex(booleans=("dex.enabled=false",))
        oauth2_proxy = self.render_oauth2_proxy(booleans=("oauth2Proxy.enabled=false",))

        self.assertEqual(dex.returncode, 0, dex.stderr)
        self.assertEqual(oauth2_proxy.returncode, 0, oauth2_proxy.stderr)

    def test_a_real_secret_beginning_with_the_placeholder_prefix_is_accepted(self):
        """The guard matches the placeholder exactly, not by prefix."""
        result = self.render_oauth2_proxy(
            "credentials.clientSecret=REPLACE_ME_BUT_I_DID",
            "credentials.cookieSecret=REPLACE_ME123456",
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_disabled_password_database_does_not_need_a_hash(self):
        """With config.enablePasswordDB=false the hash is unused, so the
        shipped placeholder must not block the external-connector flow."""
        result = self.render_dex(
            "oidcClient.secret=a-real-client-secret",
            booleans=("config.enablePasswordDB=false",),
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_incomplete_bcrypt_hash_is_rejected(self):
        """A truncated hash matches no password, so the account cannot log in."""
        for hash_value in ("$2y$12$", "$2y$12$tooshort", "notahash"):
            with self.subTest(hash=hash_value):
                result = self.render_dex(
                    "oidcClient.secret=a-real-secret",
                    f"staticPassword.hash={hash_value}",
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("not a complete bcrypt hash", result.stderr)

    def test_complete_bcrypt_hash_is_accepted(self):
        result = self.render_dex(
            "oidcClient.secret=a-real-secret",
            f"staticPassword.hash={VALID_BCRYPT_HASH}",
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cookie_secret_matches_what_oauth2_proxy_accepts(self):
        """Mirror encryption.SecretBytes.

        It strips padding, decodes with unpadded URL-safe base64, and uses the
        decoded bytes only when they are a valid AES key length; otherwise it
        uses the raw string. Both alphabets matter: a value containing + or / is
        undecodable to the URL-safe decoder and falls back to raw.
        """
        accepted = (
            ("1234567890123456", "raw 16"),
            ("123456789012345678901234", "raw 24"),
            ("12345678901234567890123456789012", "raw 32"),
            ("AAECAwQFBgcICQoLDA0ODw", "unpadded URL-safe, decodes to 16"),
            ("Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFy", "padded, decodes to 24"),
            ("aaaa/aaaa/aaaa/a", "raw 16 containing /, so the decoder falls back"),
        )
        for secret, description in accepted:
            with self.subTest(secret=description):
                result = self.render_oauth2_proxy(
                    "credentials.clientSecret=a-real-secret",
                    f"credentials.cookieSecret={secret}",
                )
                self.assertEqual(result.returncode, 0, result.stderr)

        rejected = (
            ("tooshort", "raw 8"),
            ("0123456789012345678", "raw 19"),
            (
                "//////////////////////////////////////////8=",
                "standard alphabet: the URL-safe decoder rejects /, "
                "and the 44 byte raw form is not a key length",
            ),
        )
        for secret, description in rejected:
            with self.subTest(secret=description):
                result = self.render_oauth2_proxy(
                    "credentials.clientSecret=a-real-secret",
                    f"credentials.cookieSecret={secret}",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("must be 16, 24 or 32 bytes", result.stderr)

    def test_bcrypt_cost_must_be_one_go_accepts(self):
        """Go's bcrypt allows 4 to 31; anything else cannot verify a password."""
        body = "4K/VkmDd1q1Orb3xAt82zu8gk7Ad6ReFR4LCP9UeYE90NLiN9Df72"
        for cost, valid in (
            ("04", True),
            ("12", True),
            ("31", True),
            ("03", False),
            ("32", False),
            ("99", False),
        ):
            with self.subTest(cost=cost):
                result = self.render_dex(
                    "oidcClient.secret=a-real-secret",
                    f"staticPassword.hash=$2y${cost}${body}",
                )
                if valid:
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("not a complete bcrypt hash", result.stderr)


if __name__ == "__main__":
    unittest.main()
