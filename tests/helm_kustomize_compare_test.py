#!/usr/bin/env python3

import contextlib
import copy
import importlib.util
import io
import os
import tempfile
import unittest
from pathlib import Path

import yaml

MODULE_PATH = Path(__file__).with_name("helm_kustomize_compare.py")
MODULE_SPEC = importlib.util.spec_from_file_location(
    "helm_kustomize_compare", MODULE_PATH
)
helm_kustomize_compare = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(helm_kustomize_compare)


def rules(**descriptor):
    return helm_kustomize_compare.ChartComparisonRules(descriptor)


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


DEX_CHECKSUM_RULES = {
    "knownDifferences": [
        {
            "resource": "Deployment/auth/dex",
            "ignorePodTemplateAnnotations": [
                "checksum/config",
                "checksum/oidc-client",
                "checksum/passwords",
            ],
            "reason": "test",
        }
    ]
}

DEX_CONFIG_MAP_RULES = {
    "knownDifferences": [
        {
            "resource": "ConfigMap/auth/dex",
            "compareDataAsYaml": ["config.yaml"],
            "reason": "test",
        }
    ]
}


class KnownDifferenceTest(unittest.TestCase):
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
            rules(**DEX_CONFIG_MAP_RULES).normalize(
                unquoted_username, is_helm_manifest=False
            ),
            rules(**DEX_CONFIG_MAP_RULES).normalize(
                quoted_username, is_helm_manifest=True
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
            "different kind": {**manifest, "kind": "Secret"},
            "different name": {
                **manifest,
                "metadata": {**manifest["metadata"], "name": "dex-canary"},
            },
            "different namespace": {
                **manifest,
                "metadata": {**manifest["metadata"], "namespace": "other"},
            },
        }

        for case_name, candidate in outside_scope.items():
            with self.subTest(case_name=case_name):
                normalized = rules(**DEX_CONFIG_MAP_RULES).normalize(
                    copy.deepcopy(candidate), is_helm_manifest=True
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
            rules(**DEX_CONFIG_MAP_RULES).normalize(
                malformed_config_map, is_helm_manifest=True
            )

    def test_dex_ignores_only_declared_rollout_checksum_annotations(self):
        manifest = dex_deployment_manifest()

        normalized = rules(**DEX_CHECKSUM_RULES).normalize(
            copy.deepcopy(manifest), is_helm_manifest=True
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

    def test_dex_rollout_checksums_are_scoped_to_the_named_deployment(self):
        manifest = dex_deployment_manifest()
        outside_scope = {
            "different kind": {**manifest, "kind": "StatefulSet"},
            "different name": {
                **manifest,
                "metadata": {**manifest["metadata"], "name": "dex-canary"},
            },
            "different namespace": {
                **manifest,
                "metadata": {**manifest["metadata"], "namespace": "other"},
            },
        }

        for case_name, workload in outside_scope.items():
            with self.subTest(case_name=case_name):
                normalized = rules(**DEX_CHECKSUM_RULES).normalize(
                    copy.deepcopy(workload), is_helm_manifest=True
                )
                self.assertEqual(
                    normalized["spec"]["template"]["metadata"]["annotations"],
                    manifest["spec"]["template"]["metadata"]["annotations"],
                )

    def test_a_two_segment_pattern_matches_the_kind_and_name_in_any_namespace(self):
        manifest = {
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

        normalized = rules(
            knownDifferences=[
                {
                    "resource": "Deployment/dashboard",
                    "ignorePodTemplateAnnotations": ["checksum/config"],
                    "reason": "test",
                }
            ]
        ).normalize(manifest, is_helm_manifest=True)

        self.assertEqual(
            normalized["spec"]["template"]["metadata"]["annotations"],
            {"kubectl.kubernetes.io/default-container": "dashboard"},
        )


class IgnoredLabelTest(unittest.TestCase):
    def test_pod_template_labels_are_ignored_only_when_declared(self):
        manifest = {
            "kind": "Deployment",
            "metadata": {
                "name": "katib-controller",
                "namespace": "kubeflow",
                "labels": {"app.kubernetes.io/managed-by": "Helm", "app": "katib"},
            },
            "spec": {
                "template": {
                    "metadata": {
                        "labels": {
                            "app.kubernetes.io/managed-by": "Helm",
                            "app": "katib",
                        }
                    }
                }
            },
        }

        entry = {"keys": ["app.kubernetes.io/managed-by"], "reason": "test"}

        top_level_only = rules(ignoredLabels=[entry]).normalize(
            manifest, is_helm_manifest=True
        )
        declared = rules(ignoredLabels=[dict(entry, podTemplates=True)]).normalize(
            manifest, is_helm_manifest=True
        )

        self.assertEqual(top_level_only["metadata"]["labels"], {"app": "katib"})
        self.assertEqual(
            top_level_only["spec"]["template"]["metadata"]["labels"],
            {"app.kubernetes.io/managed-by": "Helm", "app": "katib"},
        )
        self.assertEqual(declared["metadata"]["labels"], {"app": "katib"})
        self.assertEqual(
            declared["spec"]["template"]["metadata"]["labels"],
            {"app": "katib"},
        )

    def test_helm_sh_labels_and_annotations_are_always_removed(self):
        manifest = {
            "kind": "Service",
            "metadata": {
                "name": "hub",
                "labels": {"helm.sh/chart": "hub-0.1.0", "app": "hub"},
                "annotations": {
                    "meta.helm.sh/release-name": "hub",
                    "example.com/keep": "kept",
                },
            },
        }

        normalized = rules().normalize(manifest, is_helm_manifest=True)

        self.assertEqual(normalized["metadata"]["labels"], {"app": "hub"})
        self.assertEqual(
            normalized["metadata"]["annotations"], {"example.com/keep": "kept"}
        )


class ResourceKeyTest(unittest.TestCase):
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

        main_key = helm_kustomize_compare.get_resource_key(main_config_map)
        parameters_key = helm_kustomize_compare.get_resource_key(parameters_config_map)

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
        static_name_rules = rules(helmUsesKustomizeNameHashes=False)

        normalized_kustomize = static_name_rules.normalize(
            kustomize_config_map, is_helm_manifest=False
        )
        normalized_helm = static_name_rules.normalize(
            helm_config_map, is_helm_manifest=True
        )

        self.assertEqual(normalized_kustomize, normalized_helm)
        self.assertEqual(
            helm_kustomize_compare.get_resource_key(normalized_kustomize),
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
        static_name_rules = rules(helmUsesKustomizeNameHashes=False)

        normalized_kustomize = static_name_rules.normalize(
            kustomize_config_map, is_helm_manifest=False
        )
        normalized_helm = static_name_rules.normalize(
            helm_config_map, is_helm_manifest=True
        )

        self.assertEqual(normalized_kustomize, normalized_helm)
        self.assertEqual(
            helm_kustomize_compare.get_resource_key(normalized_helm),
            "ConfigMap/kubeflow/dashboard-parameters",
        )


class ControllerOwnedWebhookRulesTest(unittest.TestCase):
    def manifest(self):
        return {
            "apiVersion": "admissionregistration.k8s.io/v1",
            "kind": "MutatingWebhookConfiguration",
            "metadata": {"name": "webhook.example.com"},
            "webhooks": [
                {
                    "name": name,
                    "failurePolicy": "Fail",
                    "clientConfig": {
                        "service": {"name": "webhook", "namespace": "serving"}
                    },
                    "rules": [
                        {
                            "operations": ["CREATE"],
                            "apiGroups": ["serving.example.com"],
                            "apiVersions": ["v1"],
                            "resources": ["services"],
                        }
                    ],
                }
                for name in ("controlled.example.com", "unchanged.example.com")
            ],
        }

    def allowance(self, kind="MutatingWebhookConfiguration", names=None):
        return rules(
            knownDifferences=[
                {
                    "resource": f"{kind}/webhook.example.com",
                    "controllerOwnedWebhookRules": names or ["controlled.example.com"],
                    "reason": "The controller reconciles admission rules after installation.",
                }
            ]
        )

    def test_only_baseline_rules_are_removed_and_the_input_is_preserved(self):
        for kind in ("MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"):
            with self.subTest(kind=kind):
                baseline = self.manifest()
                baseline["kind"] = kind
                helm = copy.deepcopy(baseline)
                del helm["webhooks"][0]["rules"]
                comparison_rules = self.allowance(kind)
                normalized_helm = comparison_rules.normalize(helm, True)
                self.assertTrue(comparison_rules.unfired())
                normalized_baseline = comparison_rules.normalize(baseline, False)
                self.assertEqual(normalized_baseline, normalized_helm)
                self.assertIn("rules", baseline["webhooks"][0])
                self.assertIn("rules", normalized_baseline["webhooks"][1])
                self.assertEqual(comparison_rules.unfired(), [])

    def test_every_present_helm_rules_value_is_rejected(self):
        for value in ([], None, {}, "", [{"operations": ["CREATE"]}]):
            with self.subTest(value=value):
                manifest = self.manifest()
                manifest["webhooks"][0]["rules"] = value
                comparison_rules = self.allowance()
                with self.assertRaisesRegex(ValueError, "Helm.*omit.*rules"):
                    comparison_rules.normalize(manifest, True)
                self.assertTrue(comparison_rules.unfired())

    def test_missing_empty_or_malformed_baseline_rules_fail(self):
        for value in (None, [], {}, "rules", "absent"):
            with self.subTest(value=value):
                manifest = self.manifest()
                if value == "absent":
                    del manifest["webhooks"][0]["rules"]
                else:
                    manifest["webhooks"][0]["rules"] = value
                comparison_rules = self.allowance()
                with self.assertRaisesRegex(ValueError, "Kustomize.*non-empty.*rules"):
                    comparison_rules.normalize(manifest, False)
                self.assertTrue(comparison_rules.unfired())

    def test_missing_or_duplicate_target_fails_on_either_side(self):
        for is_helm in (False, True):
            for mode in ("missing", "duplicate", "missing-list"):
                with self.subTest(is_helm=is_helm, mode=mode):
                    manifest = self.manifest()
                    del manifest["webhooks"][0]["rules"]
                    if mode == "missing":
                        manifest["webhooks"].pop(0)
                    elif mode == "duplicate":
                        manifest["webhooks"].append(
                            copy.deepcopy(manifest["webhooks"][0])
                        )
                    else:
                        del manifest["webhooks"]
                    with self.assertRaisesRegex(ValueError, "exactly once"):
                        self.allowance().normalize(manifest, is_helm)

    def test_wrong_api_or_namespaced_target_is_rejected(self):
        for is_helm in (False, True):
            for mode in ("api", "namespace"):
                with self.subTest(is_helm=is_helm, mode=mode):
                    manifest = self.manifest()
                    if mode == "api":
                        manifest["apiVersion"] = "other.example.com/v1"
                    else:
                        manifest["metadata"]["namespace"] = "serving"
                    with self.assertRaisesRegex(
                        ValueError, "cluster-scoped.*admissionregistration"
                    ):
                        self.allowance().normalize(manifest, is_helm)

    def test_other_resource_names_and_kinds_keep_their_rules(self):
        for mode in ("name", "kind"):
            with self.subTest(mode=mode):
                manifest = self.manifest()
                if mode == "name":
                    manifest["metadata"]["name"] = "other.example.com"
                else:
                    manifest["kind"] = "ValidatingWebhookConfiguration"
                comparison_rules = self.allowance()
                self.assertEqual(comparison_rules.normalize(manifest, False), manifest)
                self.assertTrue(comparison_rules.unfired())

    def test_unintended_webhook_changes_remain_visible(self):
        for mode in ("client", "policy", "other-rules"):
            with self.subTest(mode=mode):
                baseline = self.manifest()
                helm = copy.deepcopy(baseline)
                del helm["webhooks"][0]["rules"]
                if mode == "client":
                    helm["webhooks"][0]["clientConfig"]["service"]["name"] = "other"
                elif mode == "policy":
                    helm["webhooks"][0]["failurePolicy"] = "Ignore"
                else:
                    helm["webhooks"][1]["rules"][0]["operations"] = ["DELETE"]
                comparison_rules = self.allowance()
                self.assertTrue(
                    helm_kustomize_compare.deep_diff(
                        comparison_rules.normalize(baseline, False),
                        comparison_rules.normalize(helm, True),
                    )
                )

    def test_all_declared_targets_must_validate_before_the_allowance_fires(self):
        comparison_rules = self.allowance(
            names=["controlled.example.com", "missing.example.com"]
        )
        with self.assertRaisesRegex(ValueError, "exactly once"):
            comparison_rules.normalize(self.manifest(), False)
        self.assertTrue(comparison_rules.unfired())


class ManifestSelectionTest(unittest.TestCase):
    def test_a_skip_entry_excludes_only_the_named_resource(self):
        skip_rules = rules(
            knownDifferences=[{"skip": "Namespace/istio-system", "reason": "test"}]
        )
        istio_system = {
            "kind": "Namespace",
            "metadata": {"name": "istio-system"},
        }
        other_namespace = {
            "kind": "Namespace",
            "metadata": {"name": "kubeflow"},
        }

        self.assertFalse(skip_rules.should_compare(istio_system, {}))
        self.assertTrue(skip_rules.should_compare(other_namespace, {}))

    def test_scenario_kind_selection_partitions_the_output(self):
        namespace = {"kind": "Namespace", "metadata": {"name": "kubeflow"}}
        role = {"kind": "ClusterRole", "metadata": {"name": "kubeflow-view"}}
        selection_rules = rules()

        self.assertFalse(
            selection_rules.should_compare(namespace, {"excludeKinds": ["Namespace"]})
        )
        self.assertTrue(
            selection_rules.should_compare(role, {"excludeKinds": ["Namespace"]})
        )
        self.assertTrue(
            selection_rules.should_compare(namespace, {"onlyKinds": ["Namespace"]})
        )
        self.assertFalse(
            selection_rules.should_compare(role, {"onlyKinds": ["Namespace"]})
        )

    def test_a_selection_matching_nothing_fails_instead_of_passing_empty(self):
        """A misspelled kind filters both sides to zero resources; comparing
        two empty sets must fail, not report parity."""
        namespace = {"kind": "Namespace", "metadata": {"name": "kubeflow"}}
        with tempfile.TemporaryDirectory() as directory:
            for side in ("kustomize", "helm"):
                (Path(directory) / f"{side}.yaml").write_text(yaml.safe_dump(namespace))
            kustomize_file = str(Path(directory) / "kustomize.yaml")
            helm_file = str(Path(directory) / "helm.yaml")

            self.assertFalse(
                helm_kustomize_compare.compare_manifests(
                    kustomize_file, helm_file, rules(), {"onlyKinds": ["Namespcae"]}
                )
            )
            self.assertTrue(
                helm_kustomize_compare.compare_manifests(
                    kustomize_file, helm_file, rules(), {"onlyKinds": ["Namespace"]}
                )
            )


class StalenessTest(unittest.TestCase):
    def test_an_allowance_that_never_matches_is_reported_stale(self):
        stale_rules = rules(
            knownDifferences=[{"skip": "Namespace/gone", "reason": "test"}]
        )

        stale_rules.should_compare(
            {"kind": "Namespace", "metadata": {"name": "kubeflow"}}, {}
        )

        self.assertEqual(stale_rules.unfired(), ["knownDifferences: Namespace/gone"])

    def test_a_fired_allowance_is_not_reported(self):
        fired_rules = rules(
            knownDifferences=[{"skip": "Namespace/auth", "reason": "test"}]
        )

        fired_rules.should_compare(
            {"kind": "Namespace", "metadata": {"name": "auth"}}, {}
        )

        self.assertEqual(fired_rules.unfired(), [])

    def test_every_declaration_family_reports_staleness(self):
        stale_rules = rules(
            ignoredLabels=[{"keys": ["app.kubernetes.io/managed-by"], "reason": "t"}],
            knownDifferences=[{"skip": "Namespace/gone", "reason": "t"}],
            retainedCustomResourceDefinitions={
                "reason": "t",
                "names": ["gone.example.com"],
            },
            helmOnlyResources=[{"resource": "Secret/gone", "reason": "t"}],
        )

        self.assertEqual(len(stale_rules.unfired()), 4)


class RetainedCustomResourceDefinitionTest(unittest.TestCase):
    def crd(self, name, annotations):
        return {
            "kind": "CustomResourceDefinition",
            "metadata": {"name": name, "annotations": annotations},
        }

    def test_an_undeclared_keep_annotation_fails(self):
        empty_rules = rules()

        self.assertFalse(
            empty_rules.validate_retained_custom_resource_definitions(
                [self.crd("profiles.kubeflow.org", {"helm.sh/resource-policy": "keep"})]
            )
        )

    def test_a_declared_keep_annotation_passes_and_fires(self):
        declared_rules = rules(
            retainedCustomResourceDefinitions={
                "reason": "t",
                "names": ["profiles.kubeflow.org"],
            }
        )

        self.assertTrue(
            declared_rules.validate_retained_custom_resource_definitions(
                [self.crd("profiles.kubeflow.org", {"helm.sh/resource-policy": "keep"})]
            )
        )
        self.assertEqual(declared_rules.unfired(), [])

    def test_a_declaration_without_the_annotation_goes_stale_not_green(self):
        declared_rules = rules(
            retainedCustomResourceDefinitions={
                "reason": "t",
                "names": ["profiles.kubeflow.org"],
            }
        )

        self.assertTrue(
            declared_rules.validate_retained_custom_resource_definitions(
                [self.crd("profiles.kubeflow.org", {})]
            )
        )
        self.assertEqual(
            declared_rules.unfired(),
            ["retainedCustomResourceDefinitions: profiles.kubeflow.org"],
        )


class ReleaseNamespaceTest(unittest.TestCase):
    """helmUsesReleaseNamespace fills the release namespace only for a kind
    proven namespaced: a Kubernetes built-in from the closed table, or a custom
    kind whose Namespaced CustomResourceDefinition is in the same Helm render.
    """

    @staticmethod
    def manifest(api_version, kind, name="example", namespace=None):
        metadata = {"name": name}
        if namespace is not None:
            metadata["namespace"] = namespace
        return {"apiVersion": api_version, "kind": kind, "metadata": metadata}

    @staticmethod
    def definition(group, kind, scope):
        plural = kind.lower() + "s"
        return {
            "apiVersion": "apiextensions.k8s.io/v1",
            "kind": "CustomResourceDefinition",
            "metadata": {"name": f"{plural}.{group}"},
            "spec": {
                "group": group,
                "scope": scope,
                "names": {"kind": kind, "plural": plural},
            },
        }

    def helm_key(self, manifest, render=(), **descriptor):
        descriptor.setdefault("namespace", "kubeflow")
        descriptor.setdefault("helmUsesReleaseNamespace", True)
        namespace_rules = rules(**descriptor)
        namespace_rules.observe_helm_render(list(render))
        return helm_kustomize_compare.get_resource_key(
            namespace_rules.normalize(manifest, is_helm_manifest=True)
        )

    def test_a_namespaced_built_in_kind_is_filled(self):
        self.assertEqual(
            self.helm_key(self.manifest("apps/v1", "Deployment", "controller")),
            "Deployment/kubeflow/controller",
        )
        self.assertEqual(
            self.helm_key(self.manifest("v1", "Service", "webhook")),
            "Service/kubeflow/webhook",
        )

    def test_an_explicit_namespace_is_preserved(self):
        self.assertEqual(
            self.helm_key(
                self.manifest("apps/v1", "Deployment", "controller", "other")
            ),
            "Deployment/other/controller",
        )

    def test_a_custom_kind_sharing_a_built_in_name_is_not_filled(self):
        """The table is keyed by API group as well as kind, so the core
        Service entry does not cover a custom kind named Service."""
        self.assertEqual(
            self.helm_key(self.manifest("serving.knative.dev/v1", "Service")),
            "Service/example",
        )
        self.assertEqual(
            self.helm_key(self.manifest("example.com/v1", "Deployment")),
            "Deployment/example",
        )

    def test_cluster_scoped_built_in_kinds_are_untouched(self):
        for api_version, kind in (
            ("rbac.authorization.k8s.io/v1", "ClusterRole"),
            ("rbac.authorization.k8s.io/v1", "ClusterRoleBinding"),
            ("v1", "Node"),
            ("node.k8s.io/v1", "RuntimeClass"),
            ("v1", "Namespace"),
            ("apiextensions.k8s.io/v1", "CustomResourceDefinition"),
        ):
            with self.subTest(kind=kind):
                self.assertEqual(
                    self.helm_key(self.manifest(api_version, kind)),
                    f"{kind}/example",
                )

    def test_a_cluster_scoped_custom_kind_is_untouched(self):
        cluster_issuer = self.manifest("cert-manager.io/v1", "ClusterIssuer")
        definition = self.definition("cert-manager.io", "ClusterIssuer", "Cluster")

        for render in ((), (definition,)):
            with self.subTest(definition_rendered=bool(render)):
                self.assertEqual(
                    self.helm_key(dict(cluster_issuer), render),
                    "ClusterIssuer/example",
                )

    def test_a_namespaced_custom_kind_needs_its_definition_in_the_render(self):
        application = self.manifest("sparkoperator.k8s.io/v1beta2", "SparkApplication")
        definition = self.definition(
            "sparkoperator.k8s.io", "SparkApplication", "Namespaced"
        )

        self.assertEqual(self.helm_key(dict(application)), "SparkApplication/example")
        self.assertEqual(
            self.helm_key(dict(application), (definition,)),
            "SparkApplication/kubeflow/example",
        )
        # The same kind in another API group is not proven by that definition.
        self.assertEqual(
            self.helm_key(
                self.manifest("example.com/v1", "SparkApplication"), (definition,)
            ),
            "SparkApplication/example",
        )

    def test_a_later_render_replaces_the_recorded_definitions(self):
        namespace_rules = rules(namespace="kubeflow", helmUsesReleaseNamespace=True)
        application = self.manifest("sparkoperator.k8s.io/v1beta2", "SparkApplication")
        namespace_rules.observe_helm_render(
            [self.definition("sparkoperator.k8s.io", "SparkApplication", "Namespaced")]
        )
        namespace_rules.observe_helm_render([])

        self.assertEqual(
            helm_kustomize_compare.get_resource_key(
                namespace_rules.normalize(application, is_helm_manifest=True)
            ),
            "SparkApplication/example",
        )

    def test_the_kustomize_side_and_undeclared_charts_are_untouched(self):
        namespace_rules = rules(namespace="kubeflow", helmUsesReleaseNamespace=True)
        deployment = self.manifest("apps/v1", "Deployment", "controller")

        normalized = namespace_rules.normalize(dict(deployment), is_helm_manifest=False)
        self.assertEqual(
            helm_kustomize_compare.get_resource_key(normalized),
            "Deployment/controller",
        )
        for descriptor in (
            {"helmUsesReleaseNamespace": False},
            {"helmUsesReleaseNamespace": None},
            {"helmUsesReleaseNamespace": "false"},
        ):
            with self.subTest(descriptor=descriptor):
                self.assertEqual(
                    self.helm_key(dict(deployment), **descriptor),
                    "Deployment/controller",
                )
        self.assertEqual(
            helm_kustomize_compare.get_resource_key(
                rules(namespace="kubeflow").normalize(
                    dict(deployment), is_helm_manifest=True
                )
            ),
            "Deployment/controller",
        )

    def test_compare_manifests_reads_the_definitions_from_the_helm_render(self):
        """End to end: the Helm file omits the namespace on a built-in and on
        a custom resource whose definition it carries; the Kustomize file
        writes both namespaces."""
        definition = self.definition(
            "sparkoperator.k8s.io", "SparkApplication", "Namespaced"
        )
        helm_documents = [
            definition,
            self.manifest("apps/v1", "Deployment", "controller"),
            self.manifest("sparkoperator.k8s.io/v1beta2", "SparkApplication"),
            self.manifest("rbac.authorization.k8s.io/v1", "ClusterRole", "admin"),
        ]
        kustomize_documents = [
            definition,
            self.manifest("apps/v1", "Deployment", "controller", "kubeflow"),
            self.manifest(
                "sparkoperator.k8s.io/v1beta2",
                "SparkApplication",
                "example",
                "kubeflow",
            ),
            self.manifest("rbac.authorization.k8s.io/v1", "ClusterRole", "admin"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            helm_file = os.path.join(directory, "helm.yaml")
            kustomize_file = os.path.join(directory, "kustomize.yaml")
            for path, documents in (
                (helm_file, helm_documents),
                (kustomize_file, kustomize_documents),
            ):
                with open(path, "w", encoding="utf-8") as handle:
                    yaml.safe_dump_all(documents, handle)

            with contextlib.redirect_stdout(io.StringIO()):
                declared = helm_kustomize_compare.compare_manifests(
                    kustomize_file,
                    helm_file,
                    rules(namespace="kubeflow", helmUsesReleaseNamespace=True),
                    {},
                )
                undeclared = helm_kustomize_compare.compare_manifests(
                    kustomize_file, helm_file, rules(namespace="kubeflow"), {}
                )
        self.assertTrue(declared)
        self.assertFalse(undeclared)


class HelmOnlyResourceTest(unittest.TestCase):
    def test_a_declared_extra_is_allowed_and_an_undeclared_one_is_not(self):
        extras_rules = rules(
            helmOnlyResources=[
                {"resource": "Secret/kubeflow/katib-webhook-cert", "reason": "t"}
            ]
        )

        unexpected = extras_rules.unexpected_helm_only(
            {"Secret/kubeflow/katib-webhook-cert", "Secret/kubeflow/surprise"}
        )

        self.assertEqual(unexpected, {"Secret/kubeflow/surprise"})
        self.assertEqual(extras_rules.unfired(), [])

    def test_a_wildcard_entry_matches_as_the_contract_documents(self):
        """Patterns carry * wildcards per segment, exactly as knownDifferences
        patterns do; a two-segment pattern matches any namespace."""
        extras_rules = rules(
            helmOnlyResources=[{"resource": "Secret/*-webhook-cert", "reason": "t"}]
        )

        unexpected = extras_rules.unexpected_helm_only(
            {"Secret/kubeflow/katib-webhook-cert", "Secret/kubeflow/surprise"}
        )

        self.assertEqual(unexpected, {"Secret/kubeflow/surprise"})
        self.assertEqual(extras_rules.unfired(), [])


if __name__ == "__main__":
    unittest.main()
