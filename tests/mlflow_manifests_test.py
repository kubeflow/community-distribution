#!/usr/bin/env python3

import subprocess
import unittest
import runpy

from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OVERLAY_PATH = REPOSITORY_ROOT / "applications/mlflow/overlays/kubeflow"


def render_resources():
    output = subprocess.run(
        ["kustomize", "build", str(OVERLAY_PATH)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {
        (resource["kind"], resource["metadata"]["name"]): resource
        for resource in yaml.safe_load_all(output)
        if resource
    }


class MLflowManifestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.resources = render_resources()

    def resource(self, kind, name="mlflow"):
        return self.resources[(kind, name)]

    def test_expected_workload_resources_are_present(self):
        expected_resources = {
            ("AuthorizationPolicy", "mlflow"),
            ("ClusterRole", "kubeflow-mlflow-admin"),
            ("ClusterRole", "kubeflow-mlflow-edit"),
            ("ClusterRole", "kubeflow-mlflow-view"),
            ("ClusterRole", "mlflow"),
            ("ClusterRoleBinding", "mlflow"),
            ("Deployment", "mlflow"),
            ("DestinationRule", "mlflow"),
            ("NetworkPolicy", "mlflow"),
            ("PersistentVolumeClaim", "mlflow"),
            ("Service", "mlflow"),
            ("ServiceAccount", "mlflow"),
            ("VirtualService", "mlflow"),
        }
        self.assertEqual(expected_resources, set(self.resources))

    def test_server_uses_the_release_image_and_kubeflow_configuration(self):
        container = self.resource("Deployment")["spec"]["template"]["spec"][
            "containers"
        ][0]
        self.assertEqual(
            "ghcr.io/kubeflow/mlflow-integration:v1.6.0", container["image"]
        )
        self.assertIn("--app-name=kubernetes-auth", container["args"])
        self.assertIn("--enable-workspaces", container["args"])
        self.assertIn("--workspace-store-uri=kubernetes://", container["args"])
        self.assertIn("--static-prefix=/mlflow", container["args"])
        allowed_hosts = container["args"][
            container["args"].index("--allowed-hosts") + 1
        ].split(",")
        self.assertNotIn("*", allowed_hosts)
        self.assertIn("localhost:*", allowed_hosts)
        self.assertIn("kubeflow.example.com", allowed_hosts)
        self.assertIn("*.kubeflow.example.com", allowed_hosts)

        environment = {item["name"]: item["value"] for item in container["env"]}
        self.assertEqual(
            "subject_access_review",
            environment["MLFLOW_K8S_AUTH_AUTHORIZATION_MODE"],
        )
        self.assertEqual(
            "app.kubernetes.io/part-of=kubeflow-profile",
            environment["MLFLOW_K8S_WORKSPACE_LABEL_SELECTOR"],
        )
        self.assertEqual(
            "kubeflow-userid",
            environment["MLFLOW_K8S_AUTH_REMOTE_USER_HEADER"],
        )
        self.assertEqual(
            "kubeflow-groups",
            environment["MLFLOW_K8S_AUTH_REMOTE_GROUPS_HEADER"],
        )
        self.assertEqual(
            ",",
            environment["MLFLOW_K8S_AUTH_REMOTE_GROUPS_SEPARATOR"],
        )

        self.assertEqual(
            "/mlflow/health", container["livenessProbe"]["httpGet"]["path"]
        )
        self.assertEqual(
            "/mlflow/health", container["readinessProbe"]["httpGet"]["path"]
        )

    def test_istio_routes_the_mlflow_prefix_through_the_platform_gateway(self):
        virtual_service = self.resource("VirtualService")
        self.assertEqual(["kubeflow-gateway"], virtual_service["spec"]["gateways"])
        self.assertEqual(
            ["*"],
            virtual_service["spec"]["hosts"],
        )
        matches = virtual_service["spec"]["http"][0]["match"]
        self.assertEqual(
            [{"uri": {"prefix": "/mlflow/"}}, {"uri": {"exact": "/mlflow"}}],
            matches,
        )
        destination = virtual_service["spec"]["http"][0]["route"][0]["destination"]
        self.assertEqual("mlflow.kubeflow.svc.cluster.local", destination["host"])
        self.assertEqual(5000, destination["port"]["number"])

        authorization_policy = self.resource("AuthorizationPolicy")
        principal = authorization_policy["spec"]["rules"][0]["from"][0]["source"][
            "principals"
        ]
        self.assertEqual(
            [
                "cluster.local/ns/istio-system/sa/"
                "istio-ingressgateway-service-account"
            ],
            principal,
        )

    def test_server_permissions_support_workspace_discovery_and_reviews(self):
        rules = self.resource("ClusterRole")["rules"]
        self.assertIn(
            {
                "apiGroups": [""],
                "resources": ["namespaces"],
                "verbs": ["get", "list", "watch"],
            },
            rules,
        )
        self.assertIn(
            {
                "apiGroups": ["authorization.k8s.io"],
                "resources": ["subjectaccessreviews"],
                "verbs": ["create"],
            },
            rules,
        )
        secret_rules = [rule for rule in rules if "secrets" in rule["resources"]]
        self.assertTrue(secret_rules)
        for rule in secret_rules:
            self.assertEqual(["mlflow-artifact-connection"], rule["resourceNames"])
            self.assertEqual({"get", "list", "watch"}, set(rule["verbs"]))

        subject = self.resource("ClusterRoleBinding")["subjects"][0]
        self.assertEqual(
            {"kind": "ServiceAccount", "name": "mlflow", "namespace": "kubeflow"},
            subject,
        )

    def test_profile_roles_aggregate_into_standard_kubeflow_roles(self):
        view_role = self.resource("ClusterRole", "kubeflow-mlflow-view")
        edit_role = self.resource("ClusterRole", "kubeflow-mlflow-edit")
        administrator_role = self.resource("ClusterRole", "kubeflow-mlflow-admin")

        self.assertEqual(
            "true",
            view_role["metadata"]["labels"][
                "rbac.authorization.kubeflow.org/aggregate-to-kubeflow-view"
            ],
        )
        self.assertEqual(
            "true",
            edit_role["metadata"]["labels"][
                "rbac.authorization.kubeflow.org/aggregate-to-kubeflow-edit"
            ],
        )
        self.assertEqual(
            "true",
            administrator_role["metadata"]["labels"][
                "rbac.authorization.kubeflow.org/aggregate-to-kubeflow-admin"
            ],
        )

        use_rule = next(
            rule
            for rule in edit_role["rules"]
            if "gatewaysecrets/use" in rule["resources"]
        )
        self.assertEqual(["create"], use_rule["verbs"])

    def test_local_persistence_and_network_policy_are_enabled(self):
        claim = self.resource("PersistentVolumeClaim")
        self.assertEqual("2Gi", claim["spec"]["resources"]["requests"]["storage"])
        self.assertEqual(
            ["Ingress", "Egress"], self.resource("NetworkPolicy")["spec"]["policyTypes"]
        )
        self.assertEqual("ClusterIP", self.resource("Service")["spec"]["type"])

    def test_network_ingress_is_limited_to_profiles_and_istio(self):
        ingress = self.resource("NetworkPolicy")["spec"]["ingress"]
        self.assertEqual(1, len(ingress))
        self.assertEqual(
            [
                {
                    "namespaceSelector": {
                        "matchLabels": {"app.kubernetes.io/part-of": "kubeflow-profile"}
                    }
                },
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "istio-system"}
                    }
                },
            ],
            ingress[0]["from"],
        )
        self.assertEqual(
            {5000, 15020, 15021, 15090}, {port["port"] for port in ingress[0]["ports"]}
        )

    def test_resource_measurements_include_mlflow(self):
        measurement = runpy.run_path(
            str(REPOSITORY_ROOT / "tests/metrics-server_resource_table.py")
        )
        self.assertIn("MLflow", measurement["COMPONENT_ORDER"])
        usage = measurement["parse_kubectl_output"](
            "NAMESPACE NAME CPU MEMORY\nkubeflow mlflow-server 25m 256Mi\n"
        )
        self.assertEqual({"cpu": 25, "memory": 256}, usage["MLflow"])
        self.assertEqual(
            "MLflow", measurement["categorize_resource"]("kubeflow", "mlflow")
        )


if __name__ == "__main__":
    unittest.main()
