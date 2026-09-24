#!/usr/bin/env python3
"""Test Hub credential boundaries, literal payloads and independent ownership."""

import base64
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HELM = os.environ.get("HELM_BINARY", "helm")
UNITS = (
    ("registry", "helm", "kubeflow-user-example-com", 24),
    ("catalog", "helm-catalog", "kubeflow", 10),
)


class HubChartTest(unittest.TestCase):
    def render(self, chart, namespace, *arguments):
        return subprocess.run(
            [HELM, "template", "hub", str(chart), "-n", namespace, *arguments],
            capture_output=True,
            text=True,
            check=False,
        )

    def parsed(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return [item for item in yaml.safe_load_all(result.stdout) if item]

    def test_credentials_required_for_both_charts(self):
        for _, directory, namespace, _ in UNITS:
            chart = ROOT / "applications/hub" / directory
            for arguments in ((), ("--set-string", "database.password=")):
                with self.subTest(chart=directory, arguments=arguments):
                    result = self.render(chart, namespace, *arguments)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertRegex(result.stderr, r"database[./]password")

    def test_registry_rejects_uri_delimiters_but_catalog_accepts_them(self):
        for password in (
            "has/slash",
            "has?query",
            "has#fragment",
            "has%20escape",
            "has@host",
        ):
            registry = self.render(
                ROOT / "applications/hub/helm",
                "kubeflow-user-example-com",
                "--set-string",
                "database.password=" + password,
            )
            self.assertNotEqual(registry.returncode, 0, password)
            self.assertRegex(registry.stderr, r"database[./]password")
            catalog = self.render(
                ROOT / "applications/hub/helm-catalog",
                "kubeflow",
                "--set-string",
                "database.password=" + password,
            )
            self.assertEqual(catalog.returncode, 0, catalog.stderr)

    def test_namespaces_and_scenarios_are_guarded(self):
        for _, directory, namespace, _ in UNITS:
            chart = ROOT / "applications/hub" / directory
            for target, extra in (
                ("wrong", []),
                (namespace, ["--set", "scenario=other"]),
            ):
                result = self.render(
                    chart, target, "-f", str(chart / "ci/values-platform.yaml"), *extra
                )
                self.assertNotEqual(result.returncode, 0)

    def test_default_parity_without_normalization(self):
        for mode, directory, namespace, count in UNITS:
            chart = ROOT / "applications/hub" / directory
            actual = self.parsed(
                self.render(
                    chart, namespace, "-f", str(chart / "ci/values-platform.yaml")
                )
            )
            source = subprocess.check_output(
                [
                    "kustomize",
                    "build",
                    str(ROOT / f"applications/hub/overlays/model-{mode}"),
                ],
                text=True,
            )
            baseline = [item for item in yaml.safe_load_all(source) if item]
            identity = lambda item: (
                item["apiVersion"],
                item["kind"],
                item["metadata"].get("namespace", ""),
                item["metadata"]["name"],
            )
            self.assertEqual(len(actual), count)
            self.assertEqual(
                sorted(actual, key=identity), sorted(baseline, key=identity)
            )

    def test_private_password_changes_only_password_data(self):
        for _, directory, namespace, _ in UNITS:
            chart = ROOT / "applications/hub" / directory
            args = ("-f", str(chart / "ci/values-platform.yaml"))
            baseline = self.parsed(self.render(chart, namespace, *args))
            changed = self.parsed(
                self.render(
                    chart,
                    namespace,
                    *args,
                    "--set-string",
                    "database.password=private-for-this-render",
                )
            )
            self.assertEqual(len(baseline), len(changed))
            changes = 0
            for before, after in zip(baseline, changed):
                if before == after:
                    continue
                self.assertEqual(after["kind"], "Secret")
                self.assertEqual(
                    base64.b64decode(after["data"]["POSTGRES_PASSWORD"]).decode(),
                    "private-for-this-render",
                )
                after["data"]["POSTGRES_PASSWORD"] = before["data"]["POSTGRES_PASSWORD"]
                self.assertEqual(after, before)
                changes += 1
            self.assertEqual(changes, 1)

    def test_releases_have_no_shared_identity_or_namespace_ownership(self):
        identities = []
        for _, directory, namespace, _ in UNITS:
            chart = ROOT / "applications/hub" / directory
            items = self.parsed(
                self.render(
                    chart, namespace, "-f", str(chart / "ci/values-platform.yaml")
                )
            )
            self.assertFalse(
                any(
                    item["kind"] in {"Namespace", "CustomResourceDefinition"}
                    for item in items
                )
            )
            identities.append(
                {
                    (
                        item["apiVersion"].split("/")[0],
                        item["kind"],
                        item["metadata"].get("namespace", ""),
                        item["metadata"]["name"],
                    )
                    for item in items
                }
            )
        self.assertFalse(identities[0] & identities[1])

    def test_missing_or_empty_generated_payload_fails(self):
        for _, directory, namespace, _ in UNITS:
            with tempfile.TemporaryDirectory() as temporary:
                chart = Path(temporary) / directory
                shutil.copytree(ROOT / "applications/hub" / directory, chart)
                payload = chart / "manifests/platform-resources.yaml"
                for contents in ("", "# no resources\n"):
                    payload.write_text(contents)
                    result = self.render(
                        chart, namespace, "-f", str(chart / "ci/values-platform.yaml")
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("missing or empty", result.stderr)
                payload.unlink()
                self.assertNotEqual(
                    self.render(
                        chart, namespace, "-f", str(chart / "ci/values-platform.yaml")
                    ).returncode,
                    0,
                )

    def test_embedded_helm_syntax_stays_literal(self):
        with tempfile.TemporaryDirectory() as temporary:
            chart = Path(temporary) / "helm"
            shutil.copytree(ROOT / "applications/hub/helm", chart)
            payload = chart / "manifests/platform-resources.yaml"
            payload.write_text(
                payload.read_text()
                + '\n---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: literal-test\ndata:\n  value: "{{ .Release.Name }}"\n'
            )
            objects = self.parsed(
                self.render(
                    chart,
                    "kubeflow-user-example-com",
                    "-f",
                    str(chart / "ci/values-platform.yaml"),
                )
            )
            self.assertEqual(
                next(
                    item
                    for item in objects
                    if item["metadata"]["name"] == "literal-test"
                )["data"]["value"],
                "{{ .Release.Name }}",
            )


if __name__ == "__main__":
    unittest.main()
