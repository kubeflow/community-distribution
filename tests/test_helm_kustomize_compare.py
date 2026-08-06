#!/usr/bin/env python3

import copy
import importlib.util
import unittest
from pathlib import Path

import yaml

MODULE_PATH = Path(__file__).with_name("helm_kustomize_compare.py")
WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/helm-kustomize-comparison.yml"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "helm_kustomize_compare", MODULE_PATH
)
helm_kustomize_compare = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(helm_kustomize_compare)


def dex_deployment_manifest():
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "dex",
            "namespace": "auth",
            "annotations": {
                "checksum/top-level": "keep-top-level-checksum",
                "example.com/top-level": "keep-top-level-annotation",
            },
        },
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "checksum/config": "ignore-config-checksum",
                        "checksum/oidc-client": "ignore-client-checksum",
                        "checksum/passwords": "ignore-passwords-checksum",
                        "checksum/custom": "keep-custom-checksum",
                        "example.com/pod-template": "keep-pod-annotation",
                    }
                }
            }
        },
    }


class NormalizeManifestTest(unittest.TestCase):
    def test_dex_config_map_compares_embedded_yaml_semantically(self):
        unquoted_username = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "dex", "namespace": "auth"},
            "data": {"config.yaml": "staticPasswords:\n- username: user\n"},
        }
        quoted_username = copy.deepcopy(unquoted_username)
        quoted_username["data"][
            "config.yaml"
        ] = 'staticPasswords:\n- username: "user"\n'

        self.assertEqual(
            helm_kustomize_compare.normalize_manifest(
                unquoted_username,
                component="dex",
            ),
            helm_kustomize_compare.normalize_manifest(
                quoted_username,
                component="dex",
            ),
        )

    def test_dex_config_map_yaml_parsing_is_scoped_to_exact_resource(self):
        manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "dex", "namespace": "auth"},
            "data": {"config.yaml": "staticPasswords:\n- username: user\n"},
        }
        outside_scope = {
            "different component": (manifest, "katib"),
            "different kind": ({**manifest, "kind": "Secret"}, "dex"),
            "different name": (
                {
                    **manifest,
                    "metadata": {**manifest["metadata"], "name": "dex-canary"},
                },
                "dex",
            ),
            "different namespace": (
                {
                    **manifest,
                    "metadata": {**manifest["metadata"], "namespace": "other"},
                },
                "dex",
            ),
        }

        for case_name, (candidate, component) in outside_scope.items():
            with self.subTest(case_name=case_name):
                normalized = helm_kustomize_compare.normalize_manifest(
                    copy.deepcopy(candidate),
                    component=component,
                )
                self.assertIsInstance(normalized["data"]["config.yaml"], str)

    def test_dex_config_map_rejects_malformed_embedded_yaml(self):
        malformed_config_map = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "dex", "namespace": "auth"},
            "data": {"config.yaml": "staticPasswords: [\n"},
        }

        with self.assertRaises(yaml.YAMLError):
            helm_kustomize_compare.normalize_manifest(
                malformed_config_map,
                component="dex",
            )

    def test_dex_ignores_only_known_rollout_checksum_annotations(self):
        manifest = dex_deployment_manifest()

        normalized = helm_kustomize_compare.normalize_manifest(
            copy.deepcopy(manifest), component="dex"
        )

        self.assertEqual(
            normalized["metadata"]["annotations"],
            manifest["metadata"]["annotations"],
        )
        self.assertEqual(
            normalized["spec"]["template"]["metadata"]["annotations"],
            {
                "checksum/custom": "keep-custom-checksum",
                "example.com/pod-template": "keep-pod-annotation",
            },
        )

    def test_dex_ignores_rollout_checksums_only_for_auth_namespace_deployment(self):
        manifest = dex_deployment_manifest()
        workloads_outside_dex_comparison_scope = {
            "different component": (manifest, "katib"),
            "different kind": ({**manifest, "kind": "StatefulSet"}, "dex"),
            "different name": (
                {
                    **manifest,
                    "metadata": {**manifest["metadata"], "name": "dex-canary"},
                },
                "dex",
            ),
            "different namespace": (
                {
                    **manifest,
                    "metadata": {**manifest["metadata"], "namespace": "other"},
                },
                "dex",
            ),
        }

        for case_name, (
            workload,
            component,
        ) in workloads_outside_dex_comparison_scope.items():
            with self.subTest(case_name=case_name):
                normalized_workload = helm_kustomize_compare.normalize_manifest(
                    copy.deepcopy(workload), component=component
                )
                self.assertEqual(
                    normalized_workload["spec"]["template"]["metadata"]["annotations"],
                    manifest["spec"]["template"]["metadata"]["annotations"],
                )


class OAuth2ProxyResourceKeyTest(unittest.TestCase):
    def test_parameter_config_map_does_not_collide_with_main_config_map(self):
        main_config_map = {
            "kind": "ConfigMap",
            "metadata": {
                "name": "oauth2-proxy",
                "namespace": "oauth2-proxy",
            },
        }
        parameters_config_map = {
            "kind": "ConfigMap",
            "metadata": {
                "name": "oauth2-proxy-parameters",
                "namespace": "oauth2-proxy",
            },
        }

        main_key = helm_kustomize_compare.get_resource_key(
            main_config_map,
            "oauth2-proxy",
        )
        parameters_key = helm_kustomize_compare.get_resource_key(
            parameters_config_map,
            "oauth2-proxy",
        )

        self.assertNotEqual(main_key, parameters_key)
        self.assertEqual(
            parameters_key,
            "ConfigMap/oauth2-proxy/oauth2-proxy-parameters",
        )

    def test_source_aware_normalization_matches_hashed_kustomize_config_map(self):
        kustomize_config_map = {
            "kind": "ConfigMap",
            "metadata": {
                "name": "oauth2-proxy-parameters-2m7f4h6k8b",
                "namespace": "oauth2-proxy",
            },
        }
        helm_config_map = {
            "kind": "ConfigMap",
            "metadata": {
                "name": "oauth2-proxy-parameters",
                "namespace": "oauth2-proxy",
            },
        }

        normalized_kustomize_config_map = helm_kustomize_compare.normalize_manifest(
            kustomize_config_map,
            "oauth2-proxy",
            normalize_kustomize_names=True,
        )
        normalized_helm_config_map = helm_kustomize_compare.normalize_manifest(
            helm_config_map,
            "oauth2-proxy",
            normalize_kustomize_names=False,
        )

        self.assertEqual(
            normalized_kustomize_config_map,
            normalized_helm_config_map,
        )
        self.assertEqual(
            helm_kustomize_compare.get_resource_key(
                normalized_kustomize_config_map,
                "oauth2-proxy",
            ),
            "ConfigMap/oauth2-proxy/oauth2-proxy-parameters",
        )

    def test_kustomize_volume_secret_reference_hash_is_removed(self):
        deployment = {
            "spec": {
                "template": {
                    "spec": {
                        "volumes": [
                            {
                                "name": "oauth2-proxy-config",
                                "secret": {
                                    "secretName": "oauth2-proxy-4c7m9f2k5d",
                                },
                            }
                        ]
                    }
                }
            }
        }

        normalized_deployment = helm_kustomize_compare.normalize_kustomize_refs(
            deployment
        )

        self.assertEqual(
            normalized_deployment["spec"]["template"]["spec"]["volumes"][0]["secret"][
                "secretName"
            ],
            "oauth2-proxy",
        )


class IstioManifestSelectionTest(unittest.TestCase):
    def test_only_kustomize_excludes_foundation_owned_istio_system_namespace(self):
        namespace = {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": "istio-system"},
        }

        self.assertFalse(
            helm_kustomize_compare.should_compare_manifest(
                namespace,
                component="istio",
                scenario="base",
                is_kustomize_manifest=True,
            )
        )
        self.assertTrue(
            helm_kustomize_compare.should_compare_manifest(
                namespace,
                component="istio",
                scenario="base",
                is_kustomize_manifest=False,
            )
        )


def dex_custom_resource_definition(annotations=None):
    metadata = {"name": "authcodes.dex.coreos.com"}
    if annotations is not None:
        metadata["annotations"] = annotations
    return {
        "apiVersion": "apiextensions.k8s.io/v1",
        "kind": "CustomResourceDefinition",
        "metadata": metadata,
    }


class DexCustomResourceDefinitionRetentionTest(unittest.TestCase):
    """A crds directory carries no annotation, so this check catches a move back."""

    def test_retained_definition_passes(self):
        self.assertTrue(
            helm_kustomize_compare.validate_helm_crd_resource_policies(
                [dex_custom_resource_definition({"helm.sh/resource-policy": "keep"})],
                "dex",
            )
        )

    def test_definition_without_the_retention_annotation_fails(self):
        self.assertFalse(
            helm_kustomize_compare.validate_helm_crd_resource_policies(
                [dex_custom_resource_definition()], "dex"
            )
        )

    def test_component_without_an_entry_is_not_checked(self):
        """No entry means the check is skipped, which is why this regression hid."""
        self.assertTrue(
            helm_kustomize_compare.validate_helm_crd_resource_policies(
                [dex_custom_resource_definition()], "oauth2-proxy"
            )
        )


class ComparisonWorkflowTest(unittest.TestCase):
    def test_dashboard_ignores_only_rollout_checksum_annotations(self):
        deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "dashboard", "namespace": "kubeflow"},
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "checksum/config": "rendered-checksum",
                            "kubectl.kubernetes.io/default-container": "dashboard",
                        }
                    }
                }
            },
        }

        normalized = helm_kustomize_compare.normalize_manifest(
            deployment, "kubeflow-dashboard"
        )

        self.assertEqual(
            normalized["spec"]["template"]["metadata"]["annotations"],
            {"kubectl.kubernetes.io/default-container": "dashboard"},
        )

    def test_dashboard_rollout_checksums_are_scoped_to_its_deployments(self):
        unrelated = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "poddefaults-webhook-deployment",
                "namespace": "kubeflow",
            },
            "spec": {
                "template": {
                    "metadata": {"annotations": {"checksum/config": "unchanged"}}
                }
            },
        }

        normalized = helm_kustomize_compare.normalize_manifest(
            unrelated, "kubeflow-dashboard"
        )

        self.assertEqual(
            normalized["spec"]["template"]["metadata"]["annotations"],
            {"checksum/config": "unchanged"},
        )

    def test_config_map_name_ending_in_ten_characters_is_not_truncated(self):
        """A stable chart name must not lose a legitimate final segment.

        "dashboard-parameters" ends in exactly ten lowercase alphanumeric
        characters, which is indistinguishable from a Kustomize content hash.
        Only the Kustomize side carries a real hash, so only that side is
        normalized.
        """
        kustomize_config_map = {
            "kind": "ConfigMap",
            "metadata": {
                "name": "dashboard-parameters-ckkh684h89",
                "namespace": "kubeflow",
            },
        }
        helm_config_map = {
            "kind": "ConfigMap",
            "metadata": {
                "name": "dashboard-parameters",
                "namespace": "kubeflow",
            },
        }

        normalized_kustomize = helm_kustomize_compare.normalize_manifest(
            kustomize_config_map,
            "kubeflow-dashboard",
            normalize_kustomize_names=True,
        )
        normalized_helm = helm_kustomize_compare.normalize_manifest(
            helm_config_map,
            "kubeflow-dashboard",
            normalize_kustomize_names=(
                helm_kustomize_compare.helm_uses_kustomize_generated_names(
                    "kubeflow-dashboard"
                )
            ),
        )

        self.assertEqual(normalized_kustomize, normalized_helm)
        self.assertEqual(
            helm_kustomize_compare.get_resource_key(
                normalized_helm, "kubeflow-dashboard"
            ),
            "ConfigMap/kubeflow/dashboard-parameters",
        )

    def test_dex_checks_run_in_enforcing_job(self):
        workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
        unit_test_job = workflow["jobs"]["validate-dex-unit-tests"]
        steps_by_name = {step["name"]: step for step in unit_test_job["steps"]}
        run_commands = "\n".join(step.get("run", "") for step in unit_test_job["steps"])

        self.assertFalse(unit_test_job.get("continue-on-error", False))
        self.assertIn("./tests/kustomize_install.sh", run_commands)
        self.assertIn("python tests/test_helm_kustomize_compare.py", run_commands)
        self.assertIn("python tests/test_dex_helm_rollout_checksums.py", run_commands)
        self.assertIn("./tests/helm_kustomize_compare_all.sh dex", run_commands)
        for step_name in [
            "Install Kustomize",
            "Test Helm comparison normalization",
            "Test Dex Helm behavior",
            "Compare Dex Helm and Kustomize manifests",
        ]:
            with self.subTest(step_name=step_name):
                test_step = steps_by_name[step_name]
                self.assertFalse(test_step.get("continue-on-error", False))
                self.assertNotIn("if", test_step)

    def test_comparison_unit_tests_run_in_enforcing_job(self):
        workflow = yaml.safe_load(WORKFLOW_PATH.read_text())
        unit_test_job = workflow["jobs"]["validate-comparison-unit-tests"]

        self.assertFalse(unit_test_job.get("continue-on-error", False))
        self.assertTrue(
            any(
                "python -m unittest tests/test_helm_kustomize_compare.py"
                in step.get("run", "")
                for step in unit_test_job["steps"]
            )
        )


if __name__ == "__main__":
    unittest.main()
