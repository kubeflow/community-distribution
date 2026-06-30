#!/usr/bin/env python3

import concurrent.futures
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

import requests
import urllib3

ENDPOINT_URL = "http://localhost:8080"
DEX_USERNAME = "user@example.com"
DEX_PASSWORD = "12341234"
DEX_AUTHENTICATION_TYPE = "local"
# Matches replicas: 2 in common/dex/base/deployment.yaml.
# Use a larger burst so the replica-distribution assertion is statistically stable in CI.
PARALLEL_SESSIONS = 8
# Dex authcode garbage-collection window: authcodes must be deleted after token exchange completes.
GARBAGE_COLLECTION_WAIT_SECONDS = 90
REQUEST_TIMEOUT_SECONDS = 15
# One authentication session can perform several sequential HTTP requests:
# endpoint GET, oauth2-proxy start, Dex login GET and POST, optional approval,
# and optional recovery after a 403 response.
MAXIMUM_SEQUENTIAL_HTTP_REQUESTS_PER_SESSION = 8
PARALLEL_TEST_TIMEOUT_BUFFER_SECONDS = 30
PARALLEL_TEST_TIMEOUT_SECONDS = (
    REQUEST_TIMEOUT_SECONDS * MAXIMUM_SEQUENTIAL_HTTP_REQUESTS_PER_SESSION
    + PARALLEL_TEST_TIMEOUT_BUFFER_SECONDS
)
KUBECTL_TIMEOUT_SECONDS = 120
KUBECTL_REQUEST_TIMEOUT = "30s"

AUTHENTICATION_SUCCESS_LOG_MARKER = "login successful"
DEX_POD_SELECTOR = "app=dex"
DEX_AUTHCODE_RESOURCE = "authcodes.dex.coreos.com"


@dataclass
class ParallelAuthenticationResult:
    session_index: int
    succeeded: bool
    error_message: str = ""


class DexSessionManager:
    """
    This is a version of the KFPClientManager() which only generates the Dex session cookies.
    See https://www.kubeflow.org/docs/components/pipelines/user-guides/core-functions/connect-api/#kubeflow-platform---outside-the-cluster
    """

    def __init__(
        self,
        endpoint_url: str,
        dex_username: str,
        dex_password: str,
        dex_authentication_type: str = "local",
        skip_tls_verify: bool = False,
    ):
        """
        Initialize the DexSessionManager

        :param endpoint_url: the Kubeflow Endpoint URL
        :param skip_tls_verify: if True, skip TLS verification
        :param dex_username: the Dex username
        :param dex_password: the Dex password
        :param dex_authentication_type: the authentication type to use if Dex has multiple enabled, one of: ['ldap', 'local']
        """
        self._endpoint_url = endpoint_url
        self._skip_tls_verify = skip_tls_verify
        self._dex_username = dex_username
        self._dex_password = dex_password
        self._dex_authentication_type = dex_authentication_type

        if self._skip_tls_verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # ensure `dex_authentication_type` is valid
        if self._dex_authentication_type not in ["ldap", "local"]:
            raise ValueError(
                f"Invalid `dex_authentication_type` '{self._dex_authentication_type}', must be one of: ['ldap', 'local']"
            )

    def _request_get(
        self, session: requests.Session, request_url: str
    ) -> requests.Response:
        return session.get(
            request_url,
            allow_redirects=True,
            verify=not self._skip_tls_verify,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def _request_post(
        self, session: requests.Session, request_url: str, form_data: dict[str, str]
    ) -> requests.Response:
        return session.post(
            request_url,
            data=form_data,
            allow_redirects=True,
            verify=not self._skip_tls_verify,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _has_oauth2_session_cookie(session: requests.Session) -> bool:
        return any(cookie.name.startswith("oauth2_proxy") for cookie in session.cookies)

    def _resolve_dex_login_url(
        self, session: requests.Session, split_url_object
    ) -> str:
        """
        Given a URL object, navigate to the Dex login page and return its URL.
        Handles the optional /auth selector step before the /auth/<type>/login page.
        """
        # if we are at `../auth` path, we need to select an authentication type
        if re.search(r"/auth$", split_url_object.path):
            split_url_object = split_url_object._replace(
                path=re.sub(
                    r"/auth$",
                    f"/auth/{self._dex_authentication_type}",
                    split_url_object.path,
                )
            )

        # if we are already at `../auth/xxxx/login`, use it directly
        if re.search(r"/auth/.*/login$", split_url_object.path):
            return split_url_object.geturl()

        # otherwise follow the redirect to the login page
        response = self._request_get(session, split_url_object.geturl())
        if response.status_code != 200:
            raise RuntimeError(
                "HTTP status code "
                f"'{response.status_code}' for GET against: {split_url_object.geturl()}"
            )
        return response.url

    def get_session_cookies(self) -> str:
        """
        Get the session cookies by authenticating against Dex.
        :return: a string of session cookies in the form "key1=value1; key2=value2"
        """
        session = requests.Session()

        try:
            # GET the endpoint URL, which should redirect to Dex
            response = self._request_get(session, self._endpoint_url)
            if response.status_code in [401, 403]:
                # We may be at the oauth2-proxy sign-in page.
                # The standard path to start the sign-in flow is /oauth2/start?rd=<url>
                split_url_object = urlsplit(response.url)
                split_url_object = split_url_object._replace(
                    path="/oauth2/start",
                    query=urlencode({"rd": split_url_object.path}),
                )
                response = self._request_get(session, split_url_object.geturl())
                if response.status_code not in [200, 302]:
                    raise RuntimeError(
                        f"HTTP status code '{response.status_code}' for GET against oauth2/start"
                    )
            elif response.status_code != 200:
                raise RuntimeError(
                    f"HTTP status code '{response.status_code}' for GET against: {self._endpoint_url}"
                )

            # if we were NOT redirected, the endpoint is unsecured — no cookies needed
            if len(response.history) == 0:
                return ""

            dex_login_url = self._resolve_dex_login_url(session, urlsplit(response.url))

            # submit the login credentials
            response = self._request_post(
                session,
                dex_login_url,
                form_data={"login": self._dex_username, "password": self._dex_password},
            )

            if response.status_code == 403:
                # 403 after login POST can mean the oauth2-proxy session expired mid-flow.
                # If the redirect chain passed through /oauth2/callback and we already have
                # a valid oauth2 session cookie, we are actually authenticated — return early.
                history_urls = [h.url for h in response.history]
                if any(
                    "/oauth2/callback" in u for u in history_urls
                ) and self._has_oauth2_session_cookie(session):
                    return "; ".join(
                        [f"{cookie.name}={cookie.value}" for cookie in session.cookies]
                    )

                # Otherwise restart the oauth2 flow and retry the login once
                oauth_url = (
                    f"{urlsplit(self._endpoint_url).scheme}://"
                    f"{urlsplit(self._endpoint_url).netloc}/oauth2/start"
                )
                response = self._request_get(session, oauth_url)
                if response.status_code not in [200, 302]:
                    raise RuntimeError(
                        "HTTP status code "
                        f"'{response.status_code}' for GET against oauth2/start during 403 recovery"
                    )

                dex_login_url = self._resolve_dex_login_url(
                    session, urlsplit(response.url)
                )
                response = self._request_post(
                    session,
                    dex_login_url,
                    form_data={
                        "login": self._dex_username,
                        "password": self._dex_password,
                    },
                )

            if response.status_code != 200:
                raise RuntimeError(
                    f"HTTP status code '{response.status_code}' for POST against: {dex_login_url}"
                )

            # no redirect after login POST means credentials were invalid
            if len(response.history) == 0:
                raise RuntimeError(
                    "Authentication credentials are probably invalid - "
                    f"no redirect after POST to: {dex_login_url}"
                )

            # if we are at `../approval` path, we need to approve the login
            split_url_object = urlsplit(response.url)
            if re.search(r"/approval$", split_url_object.path):
                dex_approval_url = split_url_object.geturl()
                response = self._request_post(
                    session, dex_approval_url, form_data={"approval": "approve"}
                )
                if response.status_code != 200:
                    raise RuntimeError(
                        "HTTP status code "
                        f"'{response.status_code}' for POST against: {split_url_object.geturl()}"
                    )

            return "; ".join(
                [f"{cookie.name}={cookie.value}" for cookie in session.cookies]
            )

        except requests.RequestException as request_exception:
            raise RuntimeError(
                f"Dex authentication request failed: {request_exception}"
            ) from request_exception


def run_command(
    command_arguments: list[str], timeout_seconds: int = KUBECTL_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command_arguments,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as timeout_exception:
        raise RuntimeError(
            "Command timed out after "
            f"{timeout_seconds}s: {' '.join(command_arguments)}"
        ) from timeout_exception


def run_command_or_fail(
    command_arguments: list[str], timeout_seconds: int = KUBECTL_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess:
    command_result = run_command(command_arguments, timeout_seconds=timeout_seconds)
    if command_result.returncode != 0:
        raise RuntimeError(
            "Command failed "
            f"(rc={command_result.returncode}): {' '.join(command_arguments)}\n"
            f"stdout:\n{command_result.stdout.strip()}\n"
            f"stderr:\n{command_result.stderr.strip()}"
        )
    return command_result


def get_dex_pods(min_replicas: int = 2) -> list[str]:
    """
    Return the names of running Dex pods in the auth namespace.
    Raises if fewer than min_replicas pods are found — the parallel authentication
    test requires at least two replicas to verify cross-replica load distribution.
    """
    command_arguments = [
        "kubectl",
        "--request-timeout",
        KUBECTL_REQUEST_TIMEOUT,
        "-n",
        "auth",
        "get",
        "pods",
        "-l",
        DEX_POD_SELECTOR,
        "--field-selector=status.phase=Running",
        "-o",
        "json",
    ]
    command_result = run_command_or_fail(command_arguments)
    try:
        pod_list = json.loads(command_result.stdout)
    except json.JSONDecodeError as json_decode_error:
        raise RuntimeError(
            "Failed to parse Dex pod list JSON: " f"{json_decode_error}"
        ) from json_decode_error

    ready_pod_names = []
    for pod_item in pod_list.get("items", []):
        readiness_conditions = pod_item.get("status", {}).get("conditions", [])
        is_ready = any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in readiness_conditions
        )
        if is_ready:
            ready_pod_names.append(pod_item["metadata"]["name"])

    if len(ready_pod_names) < min_replicas:
        raise RuntimeError(
            f"Expected at least {min_replicas} Dex pods (selector: {DEX_POD_SELECTOR}) "
            f"in namespace auth, found: {ready_pod_names}. "
            "The Dex deployment at common/dex/base/deployment.yaml is configured with "
            "replicas: 2 — ensure all pods have reached the Ready state before running this test."
        )
    return ready_pod_names


def count_authentication_hits_for_pod(
    pod_name: str, relative_log_window_seconds: int
) -> int:
    """Count how many successful authentication events appear in a pod's logs."""
    command_arguments = [
        "kubectl",
        "--request-timeout",
        KUBECTL_REQUEST_TIMEOUT,
        "-n",
        "auth",
        "logs",
        pod_name,
        f"--since={relative_log_window_seconds}s",
    ]
    command_result = run_command_or_fail(command_arguments)
    return len(
        re.findall(re.escape(AUTHENTICATION_SUCCESS_LOG_MARKER), command_result.stdout)
    )


def count_authcodes_objects() -> int:
    """
    Count the number of Dex authcode CRD objects currently in the auth namespace.
    Dex creates one authcode object per login; the GC process deletes them after
    the token exchange completes. Returns 0 if no instances exist.
    """
    command_arguments = [
        "kubectl",
        "--request-timeout",
        KUBECTL_REQUEST_TIMEOUT,
        "-n",
        "auth",
        "get",
        DEX_AUTHCODE_RESOURCE,
        "-o",
        "json",
    ]
    command_result = run_command(command_arguments)
    # "no resources found" is a normal state — return 0 rather than raising
    combined_output = (command_result.stdout + "\n" + command_result.stderr).lower()
    if "no resources found" in combined_output:
        return 0
    if command_result.returncode != 0:
        raise RuntimeError(
            f"Failed to query {DEX_AUTHCODE_RESOURCE}: {command_result.stderr.strip()}"
        )
    try:
        authcode_list = json.loads(command_result.stdout)
    except json.JSONDecodeError as json_decode_error:
        raise RuntimeError(
            "Failed to parse Dex authcode JSON: " f"{json_decode_error}"
        ) from json_decode_error
    return len(authcode_list.get("items", []))


def run_single_authentication() -> str:
    manager = DexSessionManager(
        endpoint_url=ENDPOINT_URL,
        skip_tls_verify=True,
        dex_username=DEX_USERNAME,
        dex_password=DEX_PASSWORD,
        dex_authentication_type=DEX_AUTHENTICATION_TYPE,
    )
    return manager.get_session_cookies()


def run_parallel_authentication_session(
    session_index: int,
) -> ParallelAuthenticationResult:
    try:
        run_single_authentication()
        return ParallelAuthenticationResult(
            session_index=session_index,
            succeeded=True,
        )
    except Exception as authentication_exception:
        return ParallelAuthenticationResult(
            session_index=session_index,
            succeeded=False,
            error_message=str(authentication_exception),
        )


def run_parallel_validation() -> None:
    """
    Validates that:
    1. PARALLEL_SESSIONS concurrent authentication sessions all succeed against a
       multi-replica Dex deployment.
    2. Authentication traffic is distributed across at least two Dex replicas (load balancer
       is working). With no sessionAffinity on the Dex Service, the Kubernetes load
       balancer distributes connections freely, so a single burst is sufficient to
       observe both replicas receiving traffic.
    3. Dex authcode CRD objects created during the burst are garbage collected after
       the GARBAGE_COLLECTION_WAIT_SECONDS window. With storage.type=kubernetes, authcodes are
       Kubernetes CRD objects that Dex actively deletes after each token exchange.

    Requires at least 2 Dex replicas (replicas: 2 in common/dex/base/deployment.yaml).
    The relative log window is sized to cover the burst plus the garbage-collection wait plus a buffer.
    Repeated reads still observe a sliding relative window, because `kubectl logs
    --since=<N>s` is evaluated relative to the time of each call.
    """
    ready_pod_names = get_dex_pods(min_replicas=2)
    print(f"Dex pods: {ready_pod_names}")

    # Size the relative log window to cover the burst duration plus GC wait plus a
    # buffer. This reduces the chance of missing burst activity, but it does not
    # create a fixed comparison interval across multiple reads.
    relative_log_window_seconds = max(GARBAGE_COLLECTION_WAIT_SECONDS + 120, 300)

    # Snapshot state before the burst
    baseline_authentication_hits = {
        pod_name: count_authentication_hits_for_pod(
            pod_name, relative_log_window_seconds
        )
        for pod_name in ready_pod_names
    }
    authcodes_before = count_authcodes_objects()

    print(f"Running parallel authentication burst with sessions={PARALLEL_SESSIONS}")

    # Run all parallel authentication sessions and collect results
    authentication_failures = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=PARALLEL_SESSIONS
    ) as executor:
        futures = [
            executor.submit(run_parallel_authentication_session, session_index)
            for session_index in range(PARALLEL_SESSIONS)
        ]
        completed_futures = set()
        try:
            for future in concurrent.futures.as_completed(
                futures, timeout=PARALLEL_TEST_TIMEOUT_SECONDS
            ):
                completed_futures.add(future)
                authentication_result = future.result()
                if not authentication_result.succeeded:
                    authentication_failures.append(authentication_result)
        except concurrent.futures.TimeoutError as timeout_error:
            pending_futures = [
                future for future in futures if future not in completed_futures
            ]
            for future in pending_futures:
                future.cancel()
            raise RuntimeError(
                "Parallel authentication sessions exceeded the batch timeout of "
                f"{PARALLEL_TEST_TIMEOUT_SECONDS} seconds: "
                f"completed={len(completed_futures)} "
                f"pending={len(pending_futures)}"
            ) from timeout_error

    if authentication_failures:
        error_summary = "; ".join(
            [
                "session="
                f"{authentication_failure.session_index} "
                f"error={authentication_failure.error_message}"
                for authentication_failure in authentication_failures
            ]
        )
        raise RuntimeError(f"Parallel authentication session failures: {error_summary}")

    # Verify that at least two distinct replicas handled authentication requests.
    # This confirms the load balancer is distributing traffic across pods.
    # Requires sessionAffinity to be absent from the Dex Service — affinity would pin
    # all sessions from the same source IP to a single pod, defeating this check.
    post_burst_authentication_hits = {
        pod_name: count_authentication_hits_for_pod(
            pod_name, relative_log_window_seconds
        )
        for pod_name in ready_pod_names
    }
    authentication_hit_delta_by_pod = {
        pod_name: max(
            post_burst_authentication_hits[pod_name]
            - baseline_authentication_hits[pod_name],
            0,
        )
        for pod_name in ready_pod_names
    }
    print(f"Authentication hit delta by pod: {authentication_hit_delta_by_pod}")

    pods_with_authentication_hits = [
        pod_name
        for pod_name, hit_delta in authentication_hit_delta_by_pod.items()
        if hit_delta > 0
    ]
    if len(pods_with_authentication_hits) < 2:
        raise RuntimeError(
            "Expected authentication traffic across at least two Dex replicas "
            f"but observed: {authentication_hit_delta_by_pod}. "
            "Verify that the Dex Service has no sessionAffinity configured."
        )

    # Verify GC: authcodes created during the burst must be cleaned up after the wait window.
    # Dex creates one authcode CRD object per login and deletes it after the token exchange.
    # If GC is broken, authcodes accumulate indefinitely.
    authcodes_after_burst = count_authcodes_objects()
    print(
        f"Authcodes count: before={authcodes_before} after_burst={authcodes_after_burst}"
    )

    if authcodes_after_burst > authcodes_before:
        time.sleep(GARBAGE_COLLECTION_WAIT_SECONDS)
        authcodes_after_wait = count_authcodes_objects()
        print(
            f"Authcodes count after garbage-collection wait ({GARBAGE_COLLECTION_WAIT_SECONDS}s): {authcodes_after_wait}"
        )
        # The burst created new authcodes — GC must reduce the count
        if authcodes_after_wait >= authcodes_after_burst:
            raise RuntimeError(
                "Authcodes did not decrease after GC wait window — "
                "Dex GC may not be functioning correctly. "
                f"before={authcodes_before} burst={authcodes_after_burst} "
                f"after_wait={authcodes_after_wait}"
            )


def main() -> None:
    run_single_authentication()
    print("Dex single authentication validation passed")

    run_parallel_validation()
    print("Dex parallel authentication and GC validation passed")


if __name__ == "__main__":
    try:
        main()
    except Exception as authentication_exception:
        print(
            f"Dex authentication test failed: {authentication_exception}",
            file=sys.stderr,
        )
        raise SystemExit(1)
