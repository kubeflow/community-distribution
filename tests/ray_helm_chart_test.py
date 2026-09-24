#!/usr/bin/env python3
"""KubeRay wrapper defaults, definition ownership and installer boundaries."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "experimental/ray/kuberay-operator/helm"
DEFINITION_NAMES = {
    "rayclusters.ray.io",
    "rayjobs.ray.io",
    "rayservices.ray.io",
    "raycronjobs.ray.io",
}


def documents(text):
    return [item for item in yaml.load_all(text, Loader=yaml.CSafeLoader) if item]


class RayChartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.chart = Path(cls.directory.name) / "chart"
        shutil.copytree(CHART, cls.chart)
        environment = {
            **os.environ,
            "HELM_CONFIG_HOME": str(Path(cls.directory.name) / "config"),
            "HELM_CACHE_HOME": str(Path(cls.directory.name) / "cache"),
            "HELM_DATA_HOME": str(Path(cls.directory.name) / "data"),
        }
        for variable in (
            "HELM_REPOSITORY_CONFIG",
            "HELM_REPOSITORY_CACHE",
            "HELM_PLUGINS",
        ):
            environment.pop(variable, None)
        cls.environment = environment
        subprocess.run(
            [
                "helm",
                "repo",
                "add",
                "kuberay",
                "https://ray-project.github.io/kuberay-helm/",
            ],
            check=True,
            env=environment,
        )
        subprocess.run(
            ["helm", "dependency", "build", str(cls.chart)],
            check=True,
            env=environment,
        )
        cls.rendered = cls.render("--include-crds")

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    @classmethod
    def render(cls, *arguments):
        return documents(
            subprocess.check_output(
                [
                    "helm",
                    "template",
                    "kuberay-operator",
                    str(cls.chart),
                    "--namespace",
                    "kubeflow",
                    *arguments,
                ],
                text=True,
                env=cls.environment,
            )
        )

    def test_source_pin_dependency_and_lock_agree(self):
        version = re.search(
            r"^KUBERAY_RELEASE_VERSION \?= (.+)$",
            (ROOT / "experimental/ray/Makefile").read_text(),
            re.MULTILINE,
        ).group(1)
        chart = yaml.safe_load((CHART / "Chart.yaml").read_text())
        lock = yaml.safe_load((CHART / "Chart.lock").read_text())
        repository = re.search(
            r"^KUBERAY_HELM_CHART_REPO \?= (.+)$",
            (ROOT / "experimental/ray/Makefile").read_text(),
            re.MULTILINE,
        ).group(1)
        self.assertEqual(chart["dependencies"][0]["repository"], repository)
        self.assertEqual(chart["appVersion"], version)
        self.assertEqual(chart["dependencies"], lock["dependencies"])
        self.assertEqual(chart["dependencies"][0]["version"], version)
        self.assertEqual(
            (CHART / "templates/aggregated-roles.yaml").read_bytes(),
            (CHART.parent / "base/aggregated-roles.yaml").read_bytes(),
        )

    def test_all_twenty_objects_and_four_non_release_managed_definitions(self):
        self.assertEqual(len(self.rendered), 20)
        definitions = {
            item["metadata"]["name"]
            for item in self.rendered
            if item["kind"] == "CustomResourceDefinition"
        }
        self.assertEqual(definitions, DEFINITION_NAMES)
        # Upstream crds/ are not release-managed templates or uninstall hooks.
        self.assertFalse(
            any(item["kind"] == "CustomResourceDefinition" for item in self.render())
        )
        installed_definitions = documents(
            subprocess.check_output(
                ["helm", "show", "crds", str(self.chart)],
                text=True,
                env=self.environment,
            )
        )
        self.assertEqual(
            {item["metadata"]["name"] for item in installed_definitions},
            DEFINITION_NAMES,
        )
        self.assertFalse(
            any(
                "helm.sh/hook" in item["metadata"].get("annotations", {})
                for item in self.rendered
            )
        )
        self.assertNotIn("Namespace", {item["kind"] for item in self.rendered})

    def test_platform_security_and_rbac_are_preserved(self):
        deployment = next(
            item for item in self.rendered if item["kind"] == "Deployment"
        )
        pod = deployment["spec"]["template"]["spec"]
        container = pod["containers"][0]
        self.assertEqual(
            pod["securityContext"]["seccompProfile"]["type"], "RuntimeDefault"
        )
        self.assertEqual(
            container["securityContext"]["seccompProfile"]["type"], "RuntimeDefault"
        )
        self.assertFalse(container["securityContext"]["allowPrivilegeEscalation"])
        self.assertTrue(container["securityContext"]["runAsNonRoot"])
        self.assertEqual(container["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertIn(
            {"name": "ENABLE_INIT_CONTAINER_INJECTION", "value": "false"},
            container["env"],
        )
        role = next(
            item
            for item in self.rendered
            if item["kind"] == "ClusterRole"
            and item["metadata"]["name"] == "kubeflow-kuberay-admin"
        )
        self.assertNotIn("aggregationRule", role)
        self.assertEqual(role["rules"], [])

    def test_non_platform_namespace_is_rejected(self):
        result = subprocess.run(
            ["helm", "template", "kuberay-operator", str(self.chart), "-n", "default"],
            capture_output=True,
            text=True,
            env=self.environment,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("existing kubeflow namespace", result.stderr)

    def test_different_release_name_is_rejected(self):
        result = subprocess.run(
            ["helm", "template", "different", str(self.chart), "-n", "kubeflow"],
            capture_output=True,
            text=True,
            env=self.environment,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release name must be kuberay-operator", result.stderr)

    def test_upstream_image_override_does_not_change_selectors(self):
        changed = self.render("--set", "kuberay-operator.image.tag=example")
        previous = next(item for item in self.rendered if item["kind"] == "Deployment")
        current = next(item for item in changed if item["kind"] == "Deployment")
        self.assertEqual(previous["spec"]["selector"], current["spec"]["selector"])
        self.assertEqual(
            current["spec"]["template"]["spec"]["containers"][0]["image"],
            "quay.io/kuberay/operator:example",
        )


class RaySmokeOwnershipTest(unittest.TestCase):
    def run_smoke_failure(
        self,
        managed_by_helm,
        *,
        existing_fixture="",
        injection="enabled",
        read_failure="",
        definition_present=True,
        cleanup_label_changed=False,
    ):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            log = directory / "commands"
            commands = {
                "kubectl": """#!/usr/bin/env bash
printf 'kubectl %s\\n' "$*" >> "$COMMAND_LOG"
case "$*" in
  *' -f -'*) cat >/dev/null ;;
  *'patch namespace'*)
    if [[ "$CLEANUP_LABEL_CHANGED" == true ]]; then exit 1; fi ;;
  *'get crd rayclusters.ray.io'*)
    if [[ "$FIXTURE_READ_FAILURE" == definition ]]; then exit 45; fi
    if [[ "$DEFINITION_PRESENT" == true ]]; then echo customresourcedefinition.apiextensions.k8s.io/rayclusters.ray.io; fi ;;
  *'get namespace'*'metadata.uid'*) printf 'profile-namespace-uid' ;;
  *'get namespace'*'jsonpath='*) printf '%s' "$ISTIO_INJECTION" ;;
  *'get raycluster kubeflow-raycluster'*)
    [[ "$EXISTING_FIXTURE" == raycluster/kubeflow-raycluster ]]; exit $? ;;
  *'get raycluster'*|*'get authorizationpolicy'*|*'get service/'*)
    if [[ "$FIXTURE_READ_FAILURE" == fixture ]]; then exit 45; fi
    if [[ -n "$EXISTING_FIXTURE" && "$*" == *"$EXISTING_FIXTURE"* ]]; then echo "$EXISTING_FIXTURE"; fi ;;
  *'get pods'*) if [[ -e "$COMMAND_LOG.failed" ]]; then echo '{"items":[]}'; else echo '{"items":[{},{}]}'; fi ;;
  *'exec -i'*) cat >/dev/null; touch "$COMMAND_LOG.failed"; exit 42 ;;
esac
""",
                "kustomize": """#!/usr/bin/env bash
printf 'kustomize %s\\n' "$*" >> "$COMMAND_LOG"
echo 'apiVersion: v1'
""",
            }
            for name, body in commands.items():
                executable = directory / name
                executable.write_text(body)
                executable.chmod(0o755)
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "experimental/ray/test.sh"),
                    "kubeflow-user-example-com",
                ],
                env={
                    **os.environ,
                    "PATH": f"{directory}:{os.environ['PATH']}",
                    "COMMAND_LOG": str(log),
                    "RAY_MANAGED_BY_HELM": managed_by_helm,
                    "EXISTING_FIXTURE": existing_fixture,
                    "ISTIO_INJECTION": injection,
                    "FIXTURE_READ_FAILURE": read_failure,
                    "DEFINITION_PRESENT": str(definition_present).lower(),
                    "CLEANUP_LABEL_CHANGED": str(cleanup_label_changed).lower(),
                },
                capture_output=True,
                text=True,
            )
            return result, log.read_text() if log.exists() else ""

    def test_helm_failure_cleans_its_fixture_without_deleting_operator_or_definitions(
        self,
    ):
        result, commands = self.run_smoke_failure("true")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertIn("delete -f raycluster_example.yaml", commands)
        self.assertIn(
            "get pods -l ray.io/cluster=kubeflow-raycluster -o json", commands
        )
        self.assertNotIn("kustomize", commands)
        self.assertNotIn("kubectl -n kubeflow delete", commands)

    def test_legacy_path_still_installs_and_removes_its_operator(self):
        result, commands = self.run_smoke_failure("false")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(
            commands.count("kustomize build kuberay-operator/overlays/kubeflow"), 2
        )
        self.assertIn("kubectl -n kubeflow delete", commands)

    def test_every_existing_fixture_identity_refuses_mutation_and_cleanup(self):
        for identity in (
            "raycluster/kubeflow-raycluster",
            "authorizationpolicy.security.istio.io/allow-ray-workers-head",
            "service/raycluster-istio-headless-svc",
        ):
            with self.subTest(identity=identity):
                result, commands = self.run_smoke_failure(
                    "true", existing_fixture=identity
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("already exists", result.stderr)
                self.assertNotIn("apply", commands)
                self.assertNotIn("delete", commands)
                self.assertNotIn("label namespace", commands)

    def test_failed_fixture_read_is_not_treated_as_absence(self):
        for read_failure in ("definition", "fixture"):
            with self.subTest(read_failure=read_failure):
                result, commands = self.run_smoke_failure(
                    "true", read_failure=read_failure
                )
                self.assertEqual(result.returncode, 45, result.stderr)
                self.assertNotIn("apply", commands)
                self.assertNotIn("delete", commands)

    def test_legacy_first_install_can_start_without_ray_definitions(self):
        result, commands = self.run_smoke_failure("false", definition_present=False)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertNotIn("get raycluster/", commands)
        self.assertIn("get authorizationpolicy.security.istio.io/", commands)
        self.assertIn("get service/", commands)

    def test_profile_injection_is_required_and_never_overwritten(self):
        for injection in ("disabled", "unexpected"):
            with self.subTest(injection=injection):
                result, commands = self.run_smoke_failure("true", injection=injection)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("istio-injection=enabled", result.stderr)
                self.assertNotIn("apply", commands)
                self.assertNotIn("delete", commands)
                self.assertNotIn("label namespace", commands)
        result, commands = self.run_smoke_failure("true")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertNotIn("label namespace", commands)
        self.assertNotIn("patch namespace", commands)

    def test_missing_profile_label_is_temporary_and_cleanup_checks_its_identity(self):
        result, commands = self.run_smoke_failure("true", injection="")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertIn(
            "label namespace kubeflow-user-example-com istio-injection=enabled",
            commands,
        )
        self.assertNotIn("--overwrite", commands)
        self.assertIn("patch namespace kubeflow-user-example-com --type=json", commands)
        self.assertIn(
            '"path":"/metadata/uid","value":"profile-namespace-uid"', commands
        )
        self.assertIn(
            '"op":"test","path":"/metadata/labels/istio-injection","value":"enabled"',
            commands,
        )
        self.assertIn(
            '"op":"remove","path":"/metadata/labels/istio-injection"', commands
        )

    def test_namespace_cleanup_precondition_failure_is_not_overridden(self):
        result, commands = self.run_smoke_failure(
            "true", injection="", cleanup_label_changed=True
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(commands.count("patch namespace"), 1)
        self.assertEqual(commands.count("label namespace"), 1)
        self.assertNotIn("--overwrite", commands)
        patch = json.loads(
            next(
                command.split(" --patch ", 1)[1]
                for command in commands.splitlines()
                if "patch namespace" in command
            )
        )
        self.assertEqual(
            patch,
            [
                {
                    "op": "test",
                    "path": "/metadata/uid",
                    "value": "profile-namespace-uid",
                },
                {
                    "op": "test",
                    "path": "/metadata/labels/istio-injection",
                    "value": "enabled",
                },
                {"op": "remove", "path": "/metadata/labels/istio-injection"},
            ],
        )

    def test_invalid_ownership_mode_is_rejected_before_cluster_access(self):
        result, commands = self.run_smoke_failure("unexpected")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(commands, "")


class RayHelmEnvironmentTest(unittest.TestCase):
    OVERRIDES = ("HELM_REPOSITORY_CONFIG", "HELM_REPOSITORY_CACHE", "HELM_PLUGINS")

    def test_chart_setup_discards_inherited_helm_overrides(self):
        inherited = {variable: "/caller/" + variable for variable in self.OVERRIDES}
        try:
            with mock.patch.dict(os.environ, inherited):
                with mock.patch.object(
                    subprocess, "run", side_effect=RuntimeError("stop before Helm")
                ) as invocation:
                    with self.assertRaisesRegex(RuntimeError, "stop before Helm"):
                        RayChartTest.setUpClass()
            environment = invocation.call_args.kwargs["env"]
            self.assertFalse(set(self.OVERRIDES) & environment.keys())
            for variable in ("HELM_CONFIG_HOME", "HELM_CACHE_HOME", "HELM_DATA_HOME"):
                self.assertTrue(
                    Path(environment[variable]).is_relative_to(
                        RayChartTest.directory.name
                    )
                )
        finally:
            RayChartTest.directory.cleanup()

    def test_shell_entrypoints_discard_inherited_helm_overrides(self):
        for script in (
            "scripts/synchronize-ray-manifests.sh",
            "tests/ray_helm_install.sh",
            "tests/ray_helm_lifecycle.sh",
        ):
            with self.subTest(
                script=script
            ), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                for relative in (
                    script,
                    "scripts/library.sh",
                    "experimental/ray/Makefile",
                    "experimental/ray/kuberay-operator/base/aggregated-roles.yaml",
                ):
                    destination = root / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(ROOT / relative, destination)
                shutil.copytree(CHART, root / CHART.relative_to(ROOT))
                executable = root / "bin/helm"
                executable.parent.mkdir()
                executable.write_text(
                    "#!/usr/bin/env python3\n"
                    "import json, os, sys\n"
                    "from pathlib import Path\n"
                    "if sys.argv[1] == 'version':\n"
                    " print('v4.2.2'); sys.exit(0)\n"
                    "Path(os.environ['HELM_ENVIRONMENT_CAPTURE']).write_text(json.dumps({key: value for key, value in os.environ.items() if key.startswith('HELM_')}))\n"
                    "sys.exit(42)\n"
                )
                executable.chmod(0o755)
                capture = root / "environment.json"
                result = subprocess.run(
                    ["bash", str(root / script)],
                    env={
                        **os.environ,
                        **{
                            variable: "/caller/" + variable
                            for variable in self.OVERRIDES
                        },
                        "PATH": f"{executable.parent}:{os.environ['PATH']}",
                        "HELM_ENVIRONMENT_CAPTURE": str(capture),
                        "KUBEFLOW_SYNCHRONIZE_NO_COMMIT": "true",
                        "RUN_HELM_LIFECYCLE_TESTS": "true",
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
                environment = json.loads(capture.read_text())
                self.assertFalse(set(self.OVERRIDES) & environment.keys())
                self.assertNotEqual(
                    environment["HELM_CONFIG_HOME"], os.environ.get("HELM_CONFIG_HOME")
                )


if __name__ == "__main__":
    unittest.main()
