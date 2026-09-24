#!/usr/bin/env python3

import importlib.util
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_SCRIPT = "scripts/generate-pipelines-helm-manifests.py"
GENERATOR_PATH = REPOSITORY_ROOT / GENERATOR_SCRIPT
OUTPUT_PATH = Path("applications/pipeline/helm/manifests")
PLATFORM_DATABASE_KUSTOMIZE_PATH = Path("applications/pipeline/overlays")
PLATFORM_KUBERNETES_NATIVE_KUSTOMIZE_PATH = Path(
    "applications/pipeline/upstream/env/cert-manager/"
    "platform-agnostic-multi-user-k8s-native"
)
PAYLOAD_FILE_NAMES = [
    "common-crds.yaml",
    "common-resources.yaml",
    "platform-database-crds.yaml",
    "platform-database-resources.yaml",
    "platform-kubernetes-native-crds.yaml",
    "platform-kubernetes-native-resources.yaml",
]

SHARED_KUSTOMIZE_INPUT = """\
apiVersion: v1
kind: Service
metadata:
  name: ml-pipeline
  namespace: kubeflow
  labels:
    app: ml-pipeline
---
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: examples.kubeflow.org
spec:
  group: kubeflow.org
  names:
    kind: Example
    plural: examples
  scope: Namespaced
  versions: []
---
aggregationRule:
  clusterRoleSelectors:
  - matchLabels:
      rbac.authorization.kubeflow.org/aggregate-to-kubeflow-pipelines-edit: "true"
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kubeflow-pipelines-edit
rules: []
"""

SCENARIO_KUSTOMIZE_INPUT = """\
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: pipeline-install-config
  namespace: kubeflow
data:
  scenario: {scenario}
"""


def load_generator_module():
    if not GENERATOR_PATH.is_file():
        raise AssertionError(f"Generator file does not exist: {GENERATOR_PATH}")

    module_specification = importlib.util.spec_from_file_location(
        "generate_pipelines_helm_manifests",
        GENERATOR_PATH,
    )
    if module_specification is None or module_specification.loader is None:
        raise AssertionError(f"Cannot load generator module: {GENERATOR_PATH}")

    generator_module = importlib.util.module_from_spec(module_specification)
    module_specification.loader.exec_module(generator_module)
    return generator_module


class ResourceIdentityTest(unittest.TestCase):
    def test_resource_identity_includes_namespace_and_rejects_missing_name(self):
        generator_module = load_generator_module()
        resource = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "ml-pipeline",
                "namespace": "kubeflow",
            },
        }

        self.assertEqual(
            generator_module.resource_identity(resource),
            ("apps/v1", "Deployment", "kubeflow", "ml-pipeline"),
        )

        with self.assertRaisesRegex(ValueError, "metadata.name"):
            generator_module.resource_identity(
                {
                    "apiVersion": "apps/v1",
                    "kind": "Deployment",
                    "metadata": {"namespace": "kubeflow"},
                }
            )


class ResourceIndexTest(unittest.TestCase):
    def test_index_resources_rejects_duplicate_resource_identity(self):
        generator_module = load_generator_module()
        self.assertTrue(
            hasattr(generator_module, "index_resources"),
            "Generator must define index_resources",
        )
        duplicate_resource = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": "ml-pipeline",
                "namespace": "kubeflow",
            },
        }

        with self.assertRaisesRegex(ValueError, "Duplicate resource identity"):
            generator_module.index_resources(
                [duplicate_resource, duplicate_resource],
                "platform-database",
            )


class ScenarioPartitionTest(unittest.TestCase):
    def test_partition_scenarios_deduplicates_identical_resources(self):
        generator_module = load_generator_module()
        self.assertTrue(
            hasattr(generator_module, "partition_scenarios"),
            "Generator must define partition_scenarios",
        )

        shared_service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "ml-pipeline", "namespace": "kubeflow"},
            "spec": {"ports": [{"port": 8888}]},
        }
        database_deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "ml-pipeline", "namespace": "kubeflow"},
            "spec": {"replicas": 1},
        }
        kubernetes_native_deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "ml-pipeline", "namespace": "kubeflow"},
            "spec": {"replicas": 2},
        }
        database_crd = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {"name": "applications.app.k8s.io"},
            "spec": {},
        }
        kubernetes_native_crd = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {"name": "pipelines.pipelines.kubeflow.org"},
            "spec": {},
        }

        partitions = generator_module.partition_scenarios(
            [shared_service, database_deployment, database_crd],
            [
                shared_service,
                kubernetes_native_deployment,
                kubernetes_native_crd,
            ],
        )

        self.assertEqual(partitions["common_resources"], [shared_service])
        self.assertEqual(partitions["common_crds"], [])
        self.assertEqual(partitions["platform_database_crds"], [database_crd])
        self.assertEqual(
            partitions["platform_database_resources"],
            [database_deployment],
        )
        self.assertEqual(
            partitions["platform_kubernetes_native_crds"],
            [kubernetes_native_crd],
        )
        self.assertEqual(
            partitions["platform_kubernetes_native_resources"],
            [kubernetes_native_deployment],
        )


class HelmRenderingSafetyTest(unittest.TestCase):
    def test_payload_keeps_argo_expressions_verbatim(self):
        """Payloads are read with .Files.Get, so nothing may be escaped.

        Argo templates such as {{workflow.name}} have to survive byte for byte.
        Escaping them was only needed while payloads lived under templates/.
        """
        generator_module = load_generator_module()
        self.assertFalse(
            hasattr(generator_module, "escape_helm_delimiters"),
            "Payloads are no longer evaluated by Helm, so escaping must be gone",
        )
        resource = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "artifact-repositories"},
            "data": {
                "keyFormat": "private-artifacts/{{workflow.namespace}}/{{pod.name}}",
            },
        }

        payload = generator_module.render_partition_payload(
            [resource], "applications/pipeline/overlays"
        )

        self.assertIn("{{workflow.namespace}}", payload)
        self.assertNotIn('{{ "{{" }}', payload)

    def test_add_crd_retention_annotation_preserves_source_resource(self):
        generator_module = load_generator_module()
        self.assertTrue(
            hasattr(generator_module, "add_crd_retention_annotation"),
            "Generator must define add_crd_retention_annotation",
        )
        source_resource = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {
                "name": "applications.app.k8s.io",
                "annotations": {"example.com/source": "kustomize"},
            },
            "spec": {},
        }

        rendered_resource = generator_module.add_crd_retention_annotation(
            source_resource
        )

        self.assertNotIn(
            "helm.sh/resource-policy",
            source_resource["metadata"]["annotations"],
        )
        self.assertEqual(
            rendered_resource["metadata"]["annotations"],
            {
                "example.com/source": "kustomize",
                "helm.sh/resource-policy": "keep",
            },
        )

    def test_render_partition_payload_is_plain_yaml_with_a_header(self):
        """No {{- if }} wrapper: when a payload applies is the chart's decision."""
        generator_module = load_generator_module()
        crd_resource = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {"name": "applications.app.k8s.io"},
            "spec": {
                "description": "Literal {{workflow.name}} expression",
            },
        }

        payload = generator_module.render_partition_payload(
            [crd_resource],
            "applications/pipeline/overlays",
        )

        self.assertTrue(
            payload.startswith(
                "# Code generated by scripts/generate-pipelines-helm-manifests.py.\n"
            )
        )
        self.assertIn("helm.sh/resource-policy: keep", payload)
        self.assertIn("{{workflow.name}}", payload)
        self.assertIn(
            "# Source Kustomize path: applications/pipeline/overlays",
            payload,
        )
        self.assertNotIn("{{- if ", payload)
        self.assertNotIn("{{- end }}", payload)

    def test_write_generated_payloads_preserves_existing_directory_on_failure(self):
        generator_module = load_generator_module()
        self.assertTrue(
            hasattr(generator_module, "write_generated_payloads"),
            "Generator must define write_generated_payloads",
        )

        with tempfile.TemporaryDirectory() as temporary_directory_name:
            temporary_directory = Path(temporary_directory_name)
            output_directory = temporary_directory / "generated"
            output_directory.mkdir()
            existing_file = output_directory / "existing.yaml"
            existing_file.write_text("preserved\n")

            with self.assertRaises(TypeError):
                generator_module.write_generated_payloads(
                    {"new.yaml": object()},
                    output_directory,
                )

            self.assertEqual(existing_file.read_text(), "preserved\n")
            self.assertFalse((output_directory / "new.yaml").exists())


def cluster_role(name, **fields):
    return {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRole",
        "metadata": {"name": name},
        **fields,
    }


def aggregation_rule(role_name):
    return {
        "clusterRoleSelectors": [
            {
                "matchLabels": {
                    f"rbac.authorization.kubeflow.org/aggregate-to-{role_name}": "true"
                }
            }
        ]
    }


VIEW_RULES = [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list"]}]


class AggregatedClusterRoleRulesTest(unittest.TestCase):
    """The aggregation controller owns the rules of an aggregated ClusterRole.

    With Helm 4 server-side apply a payload that ships `rules: []` claims that
    field, and every later `helm upgrade` conflicts with
    clusterrole-aggregation-controller.
    """

    def setUp(self):
        self.generator_module = load_generator_module()
        self.assertTrue(
            hasattr(self.generator_module, "omit_empty_aggregated_cluster_role_rules"),
            "Generator must define omit_empty_aggregated_cluster_role_rules",
        )
        self.omit = self.generator_module.omit_empty_aggregated_cluster_role_rules

    def render(self, *resources):
        return self.generator_module.render_partition_payload(
            list(resources), "applications/pipeline/overlays"
        )

    def assert_unchanged(self, resource):
        self.assertEqual(self.omit(resource), resource)
        self.assertIn("\nrules: []\n", self.render(resource))

    def test_empty_rules_of_an_aggregated_cluster_role_are_omitted(self):
        for api_version in (
            "rbac.authorization.k8s.io/v1",
            "rbac.authorization.k8s.io/v1beta1",
        ):
            with self.subTest(api_version=api_version):
                source_resource = cluster_role(
                    "kubeflow-pipelines-edit",
                    aggregationRule=aggregation_rule("kubeflow-pipelines-edit"),
                    rules=[],
                )
                source_resource["apiVersion"] = api_version
                source_resource["metadata"]["labels"] = {
                    "rbac.authorization.kubeflow.org/aggregate-to-kubeflow-edit": "true"
                }

                rendered_resource = self.omit(source_resource)

                self.assertNotIn("rules", rendered_resource)
                self.assertEqual(
                    rendered_resource,
                    {
                        key: value
                        for key, value in source_resource.items()
                        if key != "rules"
                    },
                )
                self.assertEqual(source_resource["rules"], [])
                payload = self.render(source_resource)
                self.assertNotIn("rules", payload)
                self.assertIn("aggregationRule:\n", payload)
                self.assertIn("aggregate-to-kubeflow-edit: 'true'", payload)

    def test_absent_rules_stay_absent(self):
        source_resource = cluster_role(
            "kubeflow-pipelines-edit",
            aggregationRule=aggregation_rule("kubeflow-pipelines-edit"),
        )

        self.assertEqual(self.omit(source_resource), source_resource)
        self.assertNotIn("rules", self.render(source_resource))

    def test_null_rules_are_omitted_and_never_written_as_null(self):
        source_resource = cluster_role(
            "kubeflow-pipelines-view",
            aggregationRule=aggregation_rule("kubeflow-pipelines-view"),
            rules=None,
        )

        self.assertNotIn("rules", self.omit(source_resource))
        self.assertIn("rules", source_resource)
        payload = self.render(source_resource)
        self.assertNotIn("rules", payload)
        self.assertNotIn("null", payload)

    def test_nonempty_rules_of_an_aggregated_cluster_role_fail_with_its_name(self):
        source_resource = cluster_role(
            "kubeflow-pipelines-edit",
            aggregationRule=aggregation_rule("kubeflow-pipelines-edit"),
            rules=VIEW_RULES,
        )

        for transform in (self.omit, self.render):
            with self.subTest(transform=transform.__name__):
                with self.assertRaisesRegex(
                    ValueError,
                    "Aggregated ClusterRole kubeflow-pipelines-edit "
                    "has nonempty rules",
                ):
                    transform(source_resource)
        self.assertEqual(source_resource["rules"], VIEW_RULES)

    def test_nonempty_rules_fail_the_generation_of_every_payload(self):
        source_resource = cluster_role(
            "kubeflow-pipelines-edit",
            aggregationRule=aggregation_rule("kubeflow-pipelines-edit"),
            rules=VIEW_RULES,
        )

        with self.assertRaisesRegex(ValueError, "kubeflow-pipelines-edit"):
            self.generator_module.build_generated_payloads(
                [source_resource], [source_resource]
            )

    def test_ordinary_cluster_role_with_empty_rules_is_unchanged(self):
        self.assert_unchanged(cluster_role("kubeflow-pipelines-placeholder", rules=[]))

    def test_contributing_cluster_role_with_aggregate_to_labels_is_unchanged(self):
        """A label makes a role contribute; it does not make it aggregated."""
        contributing_role = cluster_role("aggregate-to-kubeflow-pipelines-edit")
        contributing_role["metadata"]["labels"] = {
            "rbac.authorization.kubeflow.org/aggregate-to-kubeflow-pipelines-edit": (
                "true"
            )
        }

        for rules in ([], VIEW_RULES):
            with self.subTest(rules=rules):
                source_resource = {**contributing_role, "rules": rules}

                self.assertEqual(self.omit(source_resource), source_resource)
                self.assertIn("\nrules:", self.render(source_resource))

    def test_namespaced_role_is_unchanged(self):
        source_resource = cluster_role(
            "kubeflow-pipelines-edit",
            aggregationRule=aggregation_rule("kubeflow-pipelines-edit"),
            rules=[],
        )
        source_resource["kind"] = "Role"
        source_resource["metadata"]["namespace"] = "kubeflow"

        self.assert_unchanged(source_resource)

    def test_cluster_role_of_another_api_group_is_unchanged(self):
        for api_version in ("authorization.openshift.io/v1", "v1"):
            with self.subTest(api_version=api_version):
                source_resource = cluster_role(
                    "kubeflow-pipelines-edit",
                    aggregationRule=aggregation_rule("kubeflow-pipelines-edit"),
                    rules=[],
                )
                source_resource["apiVersion"] = api_version

                self.assert_unchanged(source_resource)

    def test_aggregation_rule_without_selectors_is_unchanged(self):
        for invalid_aggregation_rule in (
            None,
            {},
            {"clusterRoleSelectors": None},
            {"clusterRoleSelectors": []},
            {"clusterRoleSelectors": {}},
            [],
        ):
            with self.subTest(aggregation_rule=invalid_aggregation_rule):
                self.assert_unchanged(
                    cluster_role(
                        "kubeflow-pipelines-edit",
                        aggregationRule=invalid_aggregation_rule,
                        rules=[],
                    )
                )

    def test_a_second_run_changes_nothing(self):
        source_resource = cluster_role(
            "kubeflow-pipelines-edit",
            aggregationRule=aggregation_rule("kubeflow-pipelines-edit"),
            rules=[],
        )

        first_resource = self.omit(source_resource)
        first_payload = self.render(source_resource)

        self.assertEqual(self.omit(first_resource), first_resource)
        self.assertEqual(
            self.render(
                *self.generator_module.load_yaml_resources(
                    first_payload, "first payload"
                )
            ),
            first_payload,
        )

    def test_every_other_resource_is_byte_identical_in_the_payload(self):
        """The payload equals the one of a source that never carried the field."""
        aggregated_role = cluster_role(
            "kubeflow-pipelines-view",
            aggregationRule=aggregation_rule("kubeflow-pipelines-view"),
        )
        other_resources = [
            cluster_role("kubeflow-pipelines-placeholder", rules=[]),
            cluster_role("aggregate-to-kubeflow-pipelines-view", rules=VIEW_RULES),
            {
                "apiVersion": "apiextensions.k8s.io/v1",
                "kind": "CustomResourceDefinition",
                "metadata": {"name": "applications.app.k8s.io"},
                "spec": {},
            },
            {
                "apiVersion": "admissionregistration.k8s.io/v1",
                "kind": "ValidatingWebhookConfiguration",
                "metadata": {"name": "pipelineversions.pipelines.kubeflow.org"},
                "webhooks": [{"name": "pipelineversions.kubeflow.org", "rules": []}],
            },
        ]

        self.assertEqual(
            self.render({**aggregated_role, "rules": []}, *other_resources),
            self.render(aggregated_role, *other_resources),
        )

    def test_partitioning_compares_the_source_resources(self):
        """The field is omitted at serialization only, so what the two
        scenarios have in common is decided from the Kustomize output."""
        database_role = cluster_role(
            "kubeflow-pipelines-edit",
            aggregationRule=aggregation_rule("kubeflow-pipelines-edit"),
            rules=[],
        )
        kubernetes_native_role = cluster_role(
            "kubeflow-pipelines-edit",
            aggregationRule=aggregation_rule("kubeflow-pipelines-edit"),
        )

        partitions = self.generator_module.partition_scenarios(
            [database_role], [kubernetes_native_role]
        )

        self.assertEqual(partitions["common_resources"], [])
        self.assertEqual(partitions["platform_database_resources"], [database_role])
        self.assertIn("rules", partitions["platform_database_resources"][0])
        self.assertEqual(
            partitions["platform_kubernetes_native_resources"],
            [kubernetes_native_role],
        )


class GeneratedTemplateSetTest(unittest.TestCase):
    def test_build_generated_payloads_creates_common_and_scenario_payloads(self):
        generator_module = load_generator_module()
        self.assertTrue(
            hasattr(generator_module, "build_generated_payloads"),
            "Generator must define build_generated_payloads",
        )
        shared_crd = {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {"name": "decoratorcontrollers.metacontroller.k8s.io"},
            "spec": {},
        }
        shared_service = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "ml-pipeline", "namespace": "kubeflow"},
            "spec": {},
        }
        database_application = {
            "apiVersion": "app.k8s.io/v1beta1",
            "kind": "Application",
            "metadata": {"name": "kubeflow", "namespace": "kubeflow"},
            "spec": {},
        }
        kubernetes_native_certificate = {
            "apiVersion": "cert-manager.io/v1",
            "kind": "Certificate",
            "metadata": {
                "name": "kfp-api-webhook-cert",
                "namespace": "kubeflow",
            },
            "spec": {},
        }

        generated_templates = generator_module.build_generated_payloads(
            [shared_crd, shared_service, database_application],
            [shared_crd, shared_service, kubernetes_native_certificate],
        )

        self.assertEqual(
            set(generated_templates),
            {
                "common-crds.yaml",
                "common-resources.yaml",
                "platform-database-crds.yaml",
                "platform-database-resources.yaml",
                "platform-kubernetes-native-crds.yaml",
                "platform-kubernetes-native-resources.yaml",
            },
        )
        # Payloads carry no conditions. A template under templates/ decides when
        # each one applies, so the generator does not encode chart behaviour.
        for payload in generated_templates.values():
            self.assertNotIn("{{- if ", payload)
            self.assertNotIn(".Values.", payload)
        self.assertIn(
            "kind: CustomResourceDefinition",
            generated_templates["common-crds.yaml"],
        )
        self.assertIn(
            "kind: Service",
            generated_templates["common-resources.yaml"],
        )


def write_fixture_repository(root):
    """Two tiny local Kustomize bases at the paths the generator renders."""
    for kustomize_path, scenario in (
        (PLATFORM_DATABASE_KUSTOMIZE_PATH, "platform-database"),
        (PLATFORM_KUBERNETES_NATIVE_KUSTOMIZE_PATH, "platform-k8s-native"),
    ):
        kustomize_directory = root / kustomize_path
        kustomize_directory.mkdir(parents=True)
        (kustomize_directory / "resources.yaml").write_text(
            SHARED_KUSTOMIZE_INPUT + SCENARIO_KUSTOMIZE_INPUT.format(scenario=scenario)
        )
        (kustomize_directory / "kustomization.yaml").write_text(
            "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
            "resources:\n- resources.yaml\n"
        )
    return root / PLATFORM_DATABASE_KUSTOMIZE_PATH / "resources.yaml"


def snapshot(directory):
    """Everything --check could disturb: entries, inodes, times and bytes."""
    entries = {}
    for path in [directory, *directory.rglob("*")]:
        status = path.stat()
        entries[str(path)] = (
            status.st_ino,
            status.st_mtime_ns,
            None if path.is_dir() else path.read_bytes(),
        )
    siblings = sorted(str(path) for path in directory.parent.iterdir())
    return entries, siblings


def run_generator(root, *arguments, working_directory=None):
    return subprocess.run(
        ["python3", str(GENERATOR_PATH), "--repository-root", str(root), *arguments],
        cwd=working_directory or root,
        capture_output=True,
        text=True,
    )


def advertised_repair(stderr):
    return next(
        line.split(": ", 1)[1]
        for line in stderr.splitlines()
        if line.startswith("Regenerate with: ")
    )


class FreshnessCheckTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "repository"
        self.input_path = write_fixture_repository(self.root)
        self.output_directory = self.root / OUTPUT_PATH
        generated = run_generator(self.root)
        self.assertEqual(generated.returncode, 0, generated.stderr)

    def assert_differences(self, result, expected_lines):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            [line for line in result.stderr.splitlines() if line.startswith("  ")],
            expected_lines,
        )

    def test_freshly_generated_payloads_are_fresh(self):
        result = run_generator(self.root, "--check")

        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(
            result.stdout,
            f"Kubeflow Pipelines payloads in {OUTPUT_PATH} are fresh.\n",
        )
        self.assertEqual(
            sorted(path.name for path in self.output_directory.iterdir()),
            PAYLOAD_FILE_NAMES,
        )

    def test_a_second_generation_is_byte_identical_without_aggregated_rules(self):
        def payload_bytes():
            return {
                path.name: path.read_bytes() for path in self.output_directory.iterdir()
            }

        first_generation = payload_bytes()
        self.assertIn(b"rules: []", self.input_path.read_bytes())
        self.assertIn(b"aggregationRule:", first_generation["common-resources.yaml"])
        for file_name, file_content in first_generation.items():
            with self.subTest(file_name=file_name):
                self.assertNotIn(b"rules", file_content)

        regenerated = run_generator(self.root)

        self.assertEqual(regenerated.returncode, 0, regenerated.stderr)
        self.assertEqual(payload_bytes(), first_generation)

    def test_an_edited_input_is_detected(self):
        self.input_path.write_text(
            self.input_path.read_text().replace("app: ml-pipeline", "app: renamed")
        )

        result = run_generator(self.root, "--check")

        # The Service no longer equals its counterpart of the other scenario,
        # so it leaves the common payload and enters both scenario payloads.
        self.assert_differences(
            result,
            [
                "  stale    common-resources.yaml",
                "  stale    platform-database-resources.yaml",
                "  stale    platform-kubernetes-native-resources.yaml",
            ],
        )
        self.assertIn(
            f"Regenerate with: python3 {GENERATOR_SCRIPT} "
            f"--repository-root {shlex.quote(str(self.root))}\n",
            result.stderr,
        )
        self.assertNotIn("synchronize", result.stderr)

    def test_a_line_ending_change_is_stale(self):
        """read_text would normalise CRLF away; the bytes Helm packages differ."""
        path = self.output_directory / "common-resources.yaml"
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))

        self.assert_differences(
            run_generator(self.root, "--check"),
            ["  stale    common-resources.yaml"],
        )

    def test_missing_and_extra_files_are_reported(self):
        (self.output_directory / "common-crds.yaml").unlink()
        (self.output_directory / "stray.yaml").write_text("kind: Stray\n")

        self.assert_differences(
            run_generator(self.root, "--check"),
            ["  missing  common-crds.yaml", "  extra    stray.yaml"],
        )

    def test_a_missing_output_directory_reports_every_file_missing(self):
        shutil.rmtree(self.output_directory)

        self.assert_differences(
            run_generator(self.root, "--check"),
            [f"  missing  {file_name}" for file_name in PAYLOAD_FILE_NAMES],
        )
        self.assertFalse(self.output_directory.exists())

    def test_a_render_failure_is_an_error_status_in_both_modes(self):
        (self.input_path.parent / "kustomization.yaml").write_text("resources: [\n")
        before = snapshot(self.output_directory)

        for mode in ([], ["--check"]):
            with self.subTest(mode=mode):
                result = run_generator(self.root, *mode)
                self.assertEqual((result.returncode, result.stdout), (1, ""))
                self.assertIn("ERROR: Kustomize rendering failed", result.stderr)
                self.assertEqual(snapshot(self.output_directory), before)

    def test_check_never_writes(self):
        """On a fresh and a stale tree alike: no file, inode, modification
        time or staging directory changes."""
        fresh = snapshot(self.output_directory)
        self.assertEqual(run_generator(self.root, "--check").returncode, 0)
        self.assertEqual(snapshot(self.output_directory), fresh)

        self.input_path.write_text(
            self.input_path.read_text().replace("app: ml-pipeline", "app: renamed")
        )
        (self.output_directory / "stray.yaml").write_text("kind: Stray\n")
        stale = snapshot(self.output_directory)
        self.assertEqual(run_generator(self.root, "--check").returncode, 1)
        self.assertEqual(snapshot(self.output_directory), stale)

    def test_the_requested_output_directory_is_the_one_checked(self):
        """The default directory is fresh; only the requested one is judged."""
        requested_directory = self.root.parent / "requested"

        result = run_generator(
            self.root, "--check", "--output-directory", str(requested_directory)
        )

        self.assert_differences(
            result,
            [f"  missing  {file_name}" for file_name in PAYLOAD_FILE_NAMES],
        )
        self.assertIn(f"payloads in {requested_directory} are not", result.stderr)
        self.assertFalse(requested_directory.exists())

    def test_the_advertised_repair_runs_with_paths_that_contain_spaces(self):
        """The printed command is executed as printed, from the repository
        root, although the check was typed elsewhere with relative paths, so
        resolution and quoting are part of the contract."""
        kustomize_binary = shutil.which("kustomize")
        self.assertIsNotNone(kustomize_binary, "kustomize must be on PATH")
        parent = self.root.parent
        root = parent / "repository with spaces"
        write_fixture_repository(root)
        output_directory = parent / "output with spaces" / "manifests"
        binary_directory = parent / "binaries with spaces"
        binary_directory.mkdir()
        renamed_kustomize_binary = binary_directory / "renamed-kustomize"
        os.symlink(kustomize_binary, renamed_kustomize_binary)
        options = [
            "--output-directory",
            "output with spaces/manifests",
            "--kustomize-binary",
            str(renamed_kustomize_binary),
        ]

        checked = subprocess.run(
            [
                "python3",
                str(GENERATOR_PATH),
                "--check",
                "--repository-root",
                "repository with spaces",
                *options,
            ],
            cwd=parent,
            capture_output=True,
            text=True,
        )

        self.assertEqual(checked.returncode, 1, checked.stderr)
        advertised = advertised_repair(checked.stderr)
        self.assertEqual(
            shlex.split(advertised),
            [
                "python3",
                GENERATOR_SCRIPT,
                "--repository-root",
                str(root),
                "--output-directory",
                str(output_directory),
                "--kustomize-binary",
                str(renamed_kustomize_binary),
            ],
        )

        # The fixture repository has no copy of the generator, so the relative
        # script path of the advertised command is made to resolve there.
        (root / "scripts").mkdir()
        os.symlink(GENERATOR_PATH, root / GENERATOR_SCRIPT)
        repaired = subprocess.run(
            shlex.split(advertised), cwd=root, capture_output=True, text=True
        )

        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual(
            sorted(path.name for path in output_directory.iterdir()),
            PAYLOAD_FILE_NAMES,
        )
        self.assertFalse((root / OUTPUT_PATH).exists())
        rechecked = subprocess.run(
            [*shlex.split(advertised), "--check"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        self.assertEqual((rechecked.returncode, rechecked.stderr), (0, ""))
        self.assertIn("are fresh", rechecked.stdout)

    def test_the_default_options_are_not_carried_by_the_repair(self):
        generator_module = load_generator_module()

        self.assertEqual(
            generator_module.repair_command(generator_module.parse_arguments([])),
            f"python3 {GENERATOR_SCRIPT}",
        )


if __name__ == "__main__":
    unittest.main()
