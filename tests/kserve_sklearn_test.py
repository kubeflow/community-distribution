#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""KServe sklearn prediction test.

Deploys an sklearn InferenceService via the KServe Python SDK,
waits for Ready, runs a prediction via host-based routing,
asserts the output, and cleans up.

This test is fully independent — it does not rely on any
external deployment from kserve_test.sh.

Because of the mesh-wide global-deny-all AuthorizationPolicy
(common/istio/istio-install/base/deny_all_authorizationpolicy.yaml),
the predictor pod's sidecar blocks all traffic by default.
We create a permissive ALLOW AuthorizationPolicy (rules: [{}]) on the
predictor pod. Security is enforced at the ingress gateway, which
validates the JWT via RequestAuthentication before forwarding.
"""

import os
import sys

# Install dependencies inline (replaces the deleted requirements.txt).
# This ensures pytest, kserve SDK, and other dependencies are available when
# the CI workflow calls this file via `pytest kserve_sklearn_test.py`.
os.system(
    f"{sys.executable} -m pip install -q"
    " pytest>=7.0.0 kserve>=0.16.0 kubernetes>=18.20.0 requests>=2.18.4"
)

import json
import logging
import time

import requests
from kubernetes import client
from kubernetes.client import V1ResourceRequirements

from kserve import (
    KServeClient,
    V1beta1InferenceService,
    V1beta1InferenceServiceSpec,
    V1beta1PredictorSpec,
    V1beta1SKLearnSpec,
    constants,
)

logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
AUTHORIZATION_POLICY_NAME = "allow-isvc-sklearn"
SERVICE_NAME = "isvc-sklearn"
KSERVE_TEST_NAMESPACE = os.environ.get(
    "KSERVE_TEST_NAMESPACE", "kubeflow-user-example-com"
)

IRIS_INPUT = {"instances": [[6.8, 2.8, 4.8, 1.4], [6.0, 3.4, 4.5, 1.6]]}


def restricted_container_security_context():
    return client.V1SecurityContext(
        allow_privilege_escalation=False,
        capabilities=client.V1Capabilities(drop=["ALL"]),
        run_as_non_root=True,
        run_as_user=1000,
        seccomp_profile=client.V1SeccompProfile(type="RuntimeDefault"),
    )


# ---------------------------------------------------------------------------
# Helpers (merged from tests/kserve/utils.py)
# ---------------------------------------------------------------------------
class M2mTokenNotAvailable(Exception):
    pass


def get_cluster_ip(name="istio-ingressgateway", namespace="istio-system"):
    api_instance = client.CoreV1Api(client.ApiClient())
    service = api_instance.read_namespaced_service(name, namespace)
    if service.status.load_balancer.ingress is None:
        cluster_ip = service.spec.cluster_ip
    else:
        if service.status.load_balancer.ingress[0].hostname:
            cluster_ip = service.status.load_balancer.ingress[0].hostname
        else:
            cluster_ip = service.status.load_balancer.ingress[0].ip
    return os.environ.get("KSERVE_INGRESS_HOST_PORT", cluster_ip)


def get_m2m_auth_token(env_name="KSERVE_M2M_TOKEN"):
    try:
        return os.environ[env_name]
    except KeyError:
        raise M2mTokenNotAvailable(env_name)


def predict(service_name, input_data):
    """Send a prediction request using host-based routing.

    Args:
        service_name: Name of the InferenceService.
        input_data: Dict payload (e.g. {"instances": [...]}).

    Returns:
        Parsed JSON response dict on HTTP 200.

    Raises:
        requests.HTTPError: On non-200 responses.
    """
    kfs_client = KServeClient(
        config_file=os.environ.get("KUBECONFIG", "~/.kube/config")
    )
    kfs_client.get(
        service_name,
        namespace=KSERVE_TEST_NAMESPACE,
        version=constants.KSERVE_V1BETA1_VERSION,
    )
    # Temporary sleep until https://github.com/kserve/kserve/issues/604
    time.sleep(10)
    cluster_ip = get_cluster_ip()

    host = f"{service_name}.{KSERVE_TEST_NAMESPACE}.example.com"
    headers = {
        "Host": host,
        "Content-Type": "application/json",
    }

    try:
        token = get_m2m_auth_token()
        headers["Authorization"] = f"Bearer {token}"
        logging.info("M2M Token Found.")
    except M2mTokenNotAvailable:
        logging.warning("M2M Token Not found, client authentication disabled.")

    url = f"http://{cluster_ip}/v1/models/{service_name}:predict"

    logging.info("Sending Header = %s", headers)
    logging.info("Sending url = %s", url)
    logging.info("Sending request data: %s", input_data)
    response = requests.post(url, json.dumps(input_data), headers=headers)
    logging.info(
        "Got response code %s, content %s", response.status_code, response.content
    )
    if response.status_code == 200:
        return json.loads(response.content.decode("utf-8"))
    else:
        response.raise_for_status()


# ---------------------------------------------------------------------------
# AuthorizationPolicy helpers
# ---------------------------------------------------------------------------
def create_predictor_authorization_policy(namespace):
    """Create an AuthorizationPolicy allowing traffic to the predictor pod.

    This is needed because the global-deny-all AuthorizationPolicy in
    istio-system blocks all mesh traffic by default.

    WARNING: This uses a permissive allow-all rule (rules: [{}]) because
    the predictor pod's Envoy sidecar has no RequestAuthentication
    configured, so requestPrincipals is always empty and a
    principal-based rule would never match. Security is still enforced
    at the ingress gateway, which validates the JWT via
    RequestAuthentication before forwarding traffic.
    """
    api = client.CustomObjectsApi()
    ap_body = {
        "apiVersion": "security.istio.io/v1beta1",
        "kind": "AuthorizationPolicy",
        "metadata": {
            "name": AUTHORIZATION_POLICY_NAME,
            "namespace": namespace,
        },
        "spec": {
            "action": "ALLOW",
            # WARNING: allow-all rule — the predictor sidecar has no
            # RequestAuthentication, so requestPrincipals: ["*"] cannot
            # work here. Security is enforced at the ingress gateway.
            "rules": [{}],
            "selector": {
                "matchLabels": {
                    "serving.knative.dev/service": f"{SERVICE_NAME}-predictor",
                }
            },
        },
    }
    api.create_namespaced_custom_object(
        group="security.istio.io",
        version="v1beta1",
        namespace=namespace,
        plural="authorizationpolicies",
        body=ap_body,
    )
    logging.info("Created AuthorizationPolicy %s in %s", AUTHORIZATION_POLICY_NAME, namespace)


def delete_predictor_authorization_policy(namespace):
    """Delete the predictor AuthorizationPolicy."""
    api = client.CustomObjectsApi()
    try:
        api.delete_namespaced_custom_object(
            group="security.istio.io",
            version="v1beta1",
            namespace=namespace,
            plural="authorizationpolicies",
            name=AUTHORIZATION_POLICY_NAME,
        )
        logging.info("Deleted AuthorizationPolicy %s in %s", AUTHORIZATION_POLICY_NAME, namespace)
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------
def test_sklearn_kserve():
    predictor = V1beta1PredictorSpec(
        min_replicas=1,
        sklearn=V1beta1SKLearnSpec(
            storage_uri="gs://kfserving-examples/models/sklearn/1.0/model",
            security_context=restricted_container_security_context(),
            resources=V1ResourceRequirements(
                requests={"cpu": "50m", "memory": "128Mi"},
                limits={"cpu": "100m", "memory": "256Mi"},
            ),
        ),
    )

    isvc = V1beta1InferenceService(
        api_version=constants.KSERVE_V1BETA1,
        kind="InferenceService",
        metadata=client.V1ObjectMeta(
            name=SERVICE_NAME, namespace=KSERVE_TEST_NAMESPACE
        ),
        spec=V1beta1InferenceServiceSpec(predictor=predictor),
    )

    kserve_client = KServeClient(
        config_file=os.environ.get("KUBECONFIG", "~/.kube/config")
    )

    try:
        # Create the AuthorizationPolicy BEFORE the Inference service
        # when the predictor pod comes up
        create_predictor_authorization_policy(KSERVE_TEST_NAMESPACE)

        kserve_client.create(isvc)
        kserve_client.wait_isvc_ready(
            SERVICE_NAME, namespace=KSERVE_TEST_NAMESPACE
        )

        response = predict(SERVICE_NAME, IRIS_INPUT)
        logging.info(
            "Prediction result: %s (expected [1, 1])",
            response.get("predictions"),
        )
        assert response["predictions"] == [1, 1]
        logging.info(
            "Python SDK prediction passed for %s in %s",
            SERVICE_NAME,
            KSERVE_TEST_NAMESPACE,
        )
    finally:
        kserve_client.delete(SERVICE_NAME, KSERVE_TEST_NAMESPACE)
        delete_predictor_authorization_policy(KSERVE_TEST_NAMESPACE)
