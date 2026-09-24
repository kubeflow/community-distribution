#!/usr/bin/env python3
"""Eventing core rendering and retained, controller-owned API behavior."""

import os
import copy
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "common/knative/knative-eventing/helm"


def render(*arguments, chart=CHART, namespace="kubeflow"):
    return subprocess.run(
        [
            "helm",
            "template",
            "knative-eventing",
            str(chart),
            "-n",
            namespace,
            *arguments,
        ],
        capture_output=True,
        text=True,
    )


def objects(result):
    if result.returncode:
        raise AssertionError(result.stderr)
    return [resource for resource in yaml.safe_load_all(result.stdout) if resource]


class EventingChartTest(unittest.TestCase):
    def test_payload_diff_is_limited_to_declared_controller_ownership(self):
        baseline = list(
            yaml.safe_load_all(
                subprocess.check_output(
                    ["kustomize", "build", str(CHART.parent / "overlays/security")],
                    text=True,
                )
            )
        )
        expected = {}
        for original in baseline:
            resource = copy.deepcopy(original)
            if resource["kind"] in ("Namespace", "CustomResourceDefinition"):
                resource["metadata"].setdefault("annotations", {})[
                    "helm.sh/resource-policy"
                ] = "keep"
            if resource["kind"] == "ClusterRole" and resource.get("aggregationRule"):
                self.assertEqual(resource.pop("rules"), [])
            if (
                resource["kind"] == "Deployment"
                and resource["metadata"]["name"] == "pingsource-mt-adapter"
            ):
                self.assertEqual(resource["spec"].pop("replicas"), 0)
                container = resource["spec"]["template"]["spec"]["containers"][0]
                self.assertEqual(container["name"], "dispatcher")
                by_name = {entry["name"]: entry for entry in container["env"]}
                container["env"] = [by_name["NAMESPACE"], by_name["SYSTEM_NAMESPACE"]]
            expected[(resource["kind"], resource["metadata"]["name"])] = resource
        actual = {
            (resource["kind"], resource["metadata"]["name"]): resource
            for resource in objects(render())
        }
        self.assertEqual(actual, expected)

    def test_installer_completes_or_resumes_without_pruning_complete_releases(self):
        # Exercise the real shell control flow without accessing a cluster.
        for previous in ("absent", "definitions", "complete"):
            with self.subTest(
                previous=previous
            ), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                log = temporary / "commands"
                command = temporary / "command"
                command.write_text(
                    "#!/usr/bin/env python3\n"
                    "import json, os, pathlib, sys\n"
                    "name=pathlib.Path(sys.argv[0]).name; args=sys.argv[1:]\n"
                    "with open(os.environ['COMMAND_LOG'], 'a') as stream: stream.write(json.dumps([name,*args])+'\\n')\n"
                    "if name=='helm' and args[0]=='status': sys.exit(os.environ['PREVIOUS_PHASE']=='absent')\n"
                    "if name=='helm' and args[:2]==['get','values']: print(json.dumps({'installation': {'phase':os.environ['PREVIOUS_PHASE']}}))\n"
                    "if name=='kubectl' and args[:2]==['get','deployment/pingsource-mt-adapter']: print(json.dumps({'spec': {'replicas':1}, 'status': {'availableReplicas':1}}))\n"
                )
                command.chmod(0o755)
                for name in ("helm", "kubectl"):
                    (temporary / name).symlink_to(command)
                result = subprocess.run(
                    ["bash", str(ROOT / "tests/knative_eventing_helm_install.sh")],
                    cwd=ROOT,
                    env={
                        **os.environ,
                        "PATH": str(temporary) + os.pathsep + os.environ["PATH"],
                        "COMMAND_LOG": str(log),
                        "PREVIOUS_PHASE": previous,
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                import json

                commands = [json.loads(line) for line in log.read_text().splitlines()]
                upgrades = [
                    command
                    for command in commands
                    if command[:2] == ["helm", "upgrade"]
                ]
                self.assertIn("installation.phase=complete", upgrades[-1])
                self.assertIn("--reset-values", upgrades[-1])
                self.assertEqual(
                    any(
                        "installation.phase=controllers" in command
                        for command in upgrades
                    ),
                    False,
                )
                self.assertEqual(
                    any(command[:2] == ["helm", "install"] for command in commands),
                    previous == "absent",
                )

    def test_complete_and_definition_bootstrap_have_exact_ownership(self):
        complete = objects(render())
        definitions = objects(render("--set", "installation.phase=definitions"))
        self.assertEqual(len(complete), 105)
        self.assertEqual(len(definitions), 18)
        self.assertEqual(
            {resource["kind"] for resource in definitions},
            {"Namespace", "CustomResourceDefinition"},
        )
        for resource in definitions:
            self.assertEqual(
                resource["metadata"]["annotations"]["helm.sh/resource-policy"], "keep"
            )
        self.assertEqual(
            len(
                {
                    (
                        resource["apiVersion"],
                        resource["kind"],
                        resource["metadata"].get("namespace"),
                        resource["metadata"]["name"],
                    )
                    for resource in complete
                }
            ),
            105,
        )

    def test_aggregated_roles_leave_rules_to_the_aggregation_controller(self):
        aggregated = [
            resource
            for resource in objects(render())
            if resource["kind"] == "ClusterRole" and resource.get("aggregationRule")
        ]
        self.assertEqual(len(aggregated), 5)
        for role in aggregated:
            self.assertNotIn("rules", role)

    def test_webhook_conversion_is_preserved_and_declared(self):
        definitions = [
            resource
            for resource in objects(render())
            if resource["kind"] == "CustomResourceDefinition"
        ]
        conversions = {
            resource["metadata"]["name"]: resource["spec"]["conversion"]
            for resource in definitions
            if resource["spec"].get("conversion", {}).get("strategy") == "Webhook"
        }
        self.assertEqual(
            set(conversions),
            {"pingsources.sources.knative.dev", "eventtypes.eventing.knative.dev"},
        )
        for conversion in conversions.values():
            self.assertEqual(
                conversion["webhook"]["clientConfig"]["service"]["name"],
                "eventing-webhook",
            )

    def test_namespace_and_scenario_guards(self):
        self.assertNotEqual(render(namespace="knative-eventing").returncode, 0)
        self.assertNotEqual(render("--set", "scenario=broker").returncode, 0)
        self.assertNotEqual(
            render("--set", "installation.phase=controllers").returncode, 0
        )
        namespace = next(
            resource
            for resource in objects(render())
            if resource["kind"] == "Namespace"
        )
        self.assertEqual(
            namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"],
            "restricted",
        )

    def test_payload_is_required_and_never_evaluated_as_templates(self):
        with tempfile.TemporaryDirectory() as directory:
            chart = Path(directory) / "chart"
            shutil.copytree(CHART, chart)
            payload = chart / "manifests/platform-resources.yaml"
            content = payload.read_text()
            for invalid in ("", "# generated only\n"):
                payload.write_text(invalid)
                self.assertIn("missing or empty", render(chart=chart).stderr)
            payload.unlink()
            self.assertIn("missing or empty", render(chart=chart).stderr)
            payload.write_text(
                content
                + '\n---\napiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: literal\ndata:\n  value: "{{ .Values.neverEvaluate }}"\n'
            )
            self.assertIn("{{ .Values.neverEvaluate }}", render(chart=chart).stdout)


if __name__ == "__main__":
    unittest.main()
