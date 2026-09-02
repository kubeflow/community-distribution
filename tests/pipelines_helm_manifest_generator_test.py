#!/usr/bin/env python3

import importlib.util
import tempfile
import unittest

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = REPOSITORY_ROOT / "scripts/generate-pipelines-helm-manifests.py"


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


if __name__ == "__main__":
    unittest.main()
