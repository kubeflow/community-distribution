#!/usr/bin/env python3

"""Static assertions for the KServe relocation into the kserve namespace.

Every test here guards a local patch applied on top of the synchronized
upstream subtrees. The live KinD run in tests/kserve_test.sh already proves
routing, certificate issuance for the InferenceService webhook, and the
Models Web Application API, so those properties are deliberately not
re-asserted. What remains are the regressions that a green cluster run
cannot see: resources that silently stay behind, a sidecar that is silently
not injected, a privileged workload whose pods are silently rejected, and a
namespace field the API server silently drops.
"""

import subprocess
import unittest
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

CONTROL_PLANE_DEPLOYMENTS = (
    "kserve-controller-manager",
    "kserve-localmodel-controller-manager",
    "llmisvc-controller-manager",
)

CLUSTER_SCOPED_KINDS = {
    "CustomResourceDefinition",
    "MutatingWebhookConfiguration",
    "Namespace",
    "ValidatingWebhookConfiguration",
}


def is_cluster_scoped(resource):
    resource_kind = resource.get("kind", "")
    return resource_kind.startswith("Cluster") or resource_kind in CLUSTER_SCOPED_KINDS


def render_kustomization(kustomization_path):
    completed_process = subprocess.run(
        ["kustomize", "build", str(kustomization_path)],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [
        resource
        for resource in yaml.safe_load_all(completed_process.stdout)
        if resource is not None
    ]


def find_resource(resources, kind, name):
    for resource in resources:
        if resource.get("kind") != kind:
            continue
        if resource.get("metadata", {}).get("name") == name:
            return resource
    raise AssertionError(f"Missing {kind}/{name}")


class KServeManifestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kserve_resources = render_kustomization(
            REPOSITORY_ROOT / "applications/kserve/kserve"
        )
        cls.kserve_user_interface_resources = render_kustomization(
            REPOSITORY_ROOT / "applications/kserve/kserve-ui"
        )

    def test_every_namespaced_resource_is_in_kserve(self):
        """A resource left behind in kubeflow still installs and still runs.

        Nothing in the live installation fails, so only a static sweep of the
        rendered output can prove the relocation is complete. Assert the exact
        namespace rather than the absence of the old one: a resource that
        declares no namespace at all is applied into whichever namespace the
        caller happens to be using, which is `default` for the installation
        scripts, and a check for "not kubeflow" would stay green.
        """
        for resources in (
            self.kserve_resources,
            self.kserve_user_interface_resources,
        ):
            for resource in resources:
                if is_cluster_scoped(resource):
                    continue
                self.assertEqual(
                    resource.get("metadata", {}).get("namespace"),
                    "kserve",
                    msg=(
                        f"{resource.get('kind')}/"
                        f"{resource.get('metadata', {}).get('name')} "
                        "is not in kserve"
                    ),
                )

    def test_istio_injects_the_user_interface_but_not_the_control_plane(self):
        """The kserve namespace is not injection-enabled on purpose.

        Istio then selects individual pods through the injector webhook
        objectSelector, which matches labels and ignores annotations. A
        Models Web Application carrying only the annotation therefore runs
        without a sidecar and its AuthorizationPolicy silently stops being
        enforced, while the permissive mesh keeps every cluster test green.
        """
        namespace = find_resource(self.kserve_resources, "Namespace", "kserve")
        self.assertNotIn("istio-injection", namespace["metadata"]["labels"])
        self.assertEqual(
            namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"],
            "restricted",
        )

        user_interface = find_resource(
            self.kserve_user_interface_resources,
            "Deployment",
            "kserve-models-web-application",
        )
        self.assertEqual(
            user_interface["spec"]["template"]["metadata"]["labels"].get(
                "sidecar.istio.io/inject"
            ),
            "true",
        )

        for deployment_name in CONTROL_PLANE_DEPLOYMENTS:
            deployment = find_resource(
                self.kserve_resources, "Deployment", deployment_name
            )
            pod_template = deployment["spec"]["template"]["metadata"]
            self.assertNotIn(
                "sidecar.istio.io/inject",
                pod_template.get("labels", {}),
                msg=f"{deployment_name} must not opt into sidecar injection",
            )
            self.assertEqual(
                pod_template["annotations"]["sidecar.istio.io/inject"],
                "false",
            )

    def test_storage_initializer_uses_restricted_security_context(self):
        """The storage initializer runs in user Profile namespaces.

        tests/PSS_enable.sh does not label kubeflow-user-example-com as
        restricted, so no cluster run exercises this container under the
        Pod Security Standard that real Profile namespaces enforce.

        runAsUser is deliberately absent. The image declares a numeric non-root
        user, which is what runAsNonRoot needs in order to be verified, so
        pinning the identifier here would only restate it.
        """
        storage_container = find_resource(
            self.kserve_resources, "ClusterStorageContainer", "default"
        )
        security_context = storage_container["spec"]["container"]["securityContext"]
        self.assertFalse(security_context["allowPrivilegeEscalation"])
        self.assertEqual(security_context["capabilities"]["drop"], ["ALL"])
        self.assertTrue(security_context["runAsNonRoot"])
        self.assertNotIn("runAsUser", security_context)
        self.assertEqual(security_context["seccompProfile"]["type"], "RuntimeDefault")

    def test_cluster_scoped_resources_have_no_namespace(self):
        """The API server drops metadata.namespace on cluster-scoped objects.

        A stray namespace field therefore never fails an apply and is only
        visible in the rendered manifests.
        """
        for resource in self.kserve_resources:
            resource_kind = resource.get("kind", "")
            if not is_cluster_scoped(resource):
                continue

            self.assertNotIn(
                "namespace",
                resource.get("metadata", {}),
                msg=(
                    f"{resource_kind}/"
                    f"{resource.get('metadata', {}).get('name')} is cluster-scoped"
                ),
            )

    def test_disabled_local_model_node_agent_has_no_resources(self):
        """The agent mounts a writable /models hostPath and runs privileged.

        If a synchronization restores it, restricted Pod Security rejects its
        pods, the DaemonSet creates none, and waiting for all pods to become
        ready still succeeds. Only the rendered output shows it came back.
        """
        forbidden_resources = {
            ("DaemonSet", "kserve-localmodelnode-agent"),
            ("ServiceAccount", "kserve-localmodelnode-agent"),
            ("ClusterRole", "kserve-localmodelnode-agent-role"),
            ("ClusterRoleBinding", "kserve-localmodelnode-agent-rolebinding"),
        }
        rendered_resources = {
            (resource.get("kind"), resource.get("metadata", {}).get("name"))
            for resource in self.kserve_resources
        }
        self.assertFalse(forbidden_resources & rendered_resources)

    def test_webhook_certificates_and_ca_injection_use_kserve_namespace(self):
        """The previous layout hardcoded mismatched namespaces here.

        Only the InferenceService webhook is exercised by the cluster tests;
        the llmisvc and localmodel chains are never called, so a namespace
        mismatch there surfaces first on a user cluster.
        """
        for certificate_name in (
            "serving-cert",
            "llmisvc-serving-cert",
            "localmodel-serving-cert",
        ):
            certificate = find_resource(
                self.kserve_resources, "Certificate", certificate_name
            )
            self.assertEqual(certificate["metadata"].get("namespace"), "kserve")
            self.assertTrue(
                all(
                    dns_name.endswith(".kserve.svc")
                    for dns_name in certificate["spec"].get("dnsNames", [])
                )
            )

        annotated_resources = [
            resource
            for resource in self.kserve_resources
            if resource.get("metadata", {})
            .get("annotations", {})
            .get("cert-manager.io/inject-ca-from")
        ]
        self.assertTrue(annotated_resources)
        for resource in annotated_resources:
            ca_source = resource["metadata"]["annotations"][
                "cert-manager.io/inject-ca-from"
            ]
            self.assertTrue(ca_source.startswith("kserve/"))

        webhook_service_references = []
        for resource in self.kserve_resources:
            if resource.get("kind") in (
                "MutatingWebhookConfiguration",
                "ValidatingWebhookConfiguration",
            ):
                webhook_service_references.extend(
                    webhook.get("clientConfig", {}).get("service")
                    for webhook in resource.get("webhooks", [])
                )

            if resource.get("kind") == "CustomResourceDefinition":
                webhook_service_references.append(
                    resource.get("spec", {})
                    .get("conversion", {})
                    .get("webhook", {})
                    .get("clientConfig", {})
                    .get("service")
                )

        webhook_service_references = [
            service_reference
            for service_reference in webhook_service_references
            if service_reference
        ]
        self.assertTrue(webhook_service_references)
        for service_reference in webhook_service_references:
            self.assertEqual(service_reference.get("namespace"), "kserve")


if __name__ == "__main__":
    unittest.main()
