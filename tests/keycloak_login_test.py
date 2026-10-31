#!/usr/bin/env python3
# Logs in to Kubeflow through OAuth2 Proxy and Keycloak (no Dex) like a browser,
# then calls the web applications with the session cookie.
# Setup: .github/workflows/keycloak_oauth2-proxy_test.yaml

import base64
import hashlib
import html
import re
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

KUBEFLOW_URL = "http://localhost:8080"
KEYCLOAK_ISSUER = "http://keycloak.keycloak.svc.cluster.local:8081/realms/kubeflow"
CLIENT_ID = "kubeflow"
USERNAME = "user"
PASSWORD = "12341234"
EMAIL = "user@example.com"
GROUP = "kubeflow-users"
NAMESPACE = "kubeflow-user-example-com"
# accessTokenLifespan in tests/keycloak/realm.json
TOKEN_LIFESPAN_SECONDS = 60
TIMEOUT = 15

# The client requires PKCE, so the authorization requests below need a challenge.
CODE_VERIFIER = "keycloak-test-code-verifier-0123456789abcdefghijklmnopqrstuvwxyz"
CODE_CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(CODE_VERIFIER.encode()).digest())
    .decode()
    .rstrip("=")
)

# Read-only API calls per web application. Each must return 200 for the
# profile namespace and be refused for the "kubeflow" namespace.
APPLICATION_ENDPOINTS = {
    "Pipelines": "/pipeline/apis/v2beta1/runs?namespace={namespace}",
    "Workspaces": "/workspaces/api/v1/workspaces/{namespace}",
    "Katib": "/katib/fetch_experiments/?namespace={namespace}",
    "KServe": "/kserve-endpoints/api/namespaces/{namespace}/inferenceservices",
}


def keycloak_error(extra_parameters):
    parameters = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": f"{KUBEFLOW_URL}/oauth2/callback",
        "state": "test",
        "code_challenge": CODE_CHALLENGE,
        "code_challenge_method": "S256",
        **extra_parameters,
    }
    response = requests.get(
        f"{KEYCLOAK_ISSUER}/protocol/openid-connect/auth?{urlencode(parameters)}",
        allow_redirects=False,
        timeout=TIMEOUT,
    )
    if response.status_code != 302:
        raise RuntimeError(f"expected a redirect, got {response.status_code}")
    query = parse_qs(urlsplit(response.headers["Location"]).query)
    return query.get("error", [""])[0], query.get("error_description", [""])[0]


def check_keycloak_rejects_dex_settings():
    # The base oauth2_proxy.cfg asks for the scope "groups" and sends prompt=none.
    # Both work with Dex and fail with Keycloak.
    error, description = keycloak_error({"scope": "openid profile email groups"})
    if error != "invalid_scope":
        raise RuntimeError(
            f"scope groups: expected invalid_scope, got {error} {description}"
        )
    error, description = keycloak_error({"scope": "openid", "prompt": "none"})
    if error != "login_required":
        raise RuntimeError(
            f"prompt=none: expected login_required, got {error} {description}"
        )
    print("Keycloak rejects the scope groups and prompt=none without a session")


def login():
    session = requests.Session()
    response = session.get(f"{KUBEFLOW_URL}/oauth2/start?rd=/", timeout=TIMEOUT)
    if response.status_code != 200 or not response.url.startswith(KEYCLOAK_ISSUER):
        raise RuntimeError(
            f"no Keycloak login page: {response.status_code} {response.url}"
        )
    if parse_qs(urlsplit(response.url).query).get("code_challenge_method") != ["S256"]:
        raise RuntimeError("OAuth2 Proxy did not use PKCE S256")

    form = re.search(
        r'<form[^>]*id="kc-form-login"[^>]*action="([^"]+)"', response.text
    )
    if not form:
        raise RuntimeError("Keycloak login form not found")
    response = session.post(
        html.unescape(form.group(1)),
        data={"username": USERNAME, "password": PASSWORD, "credentialId": ""},
        timeout=TIMEOUT,
    )
    if response.status_code != 200 or not any(
        "/oauth2/callback" in redirect.url for redirect in response.history
    ):
        raise RuntimeError(f"login failed: {response.status_code} {response.url}")
    print("Logged in through OAuth2 Proxy and Keycloak with PKCE S256")
    return session


def session_cookie(session):
    return "".join(
        cookie.value
        for cookie in session.cookies
        if cookie.name.startswith("oauth2_proxy_kubeflow")
    )


def check_dashboard_user(session):
    # The dashboard reads kubeflow-userid, which Istio takes from the email claim.
    response = session.get(f"{KUBEFLOW_URL}/api/workgroup/env-info", timeout=TIMEOUT)
    if response.status_code != 200 or response.json().get("user") != EMAIL:
        raise RuntimeError(f"dashboard: {response.status_code} {response.text[:300]}")


def check_claims(session):
    check_dashboard_user(session)
    response = session.get(f"{KUBEFLOW_URL}/oauth2/userinfo", timeout=TIMEOUT)
    groups = response.json().get("groups") or []
    if GROUP not in groups:
        raise RuntimeError(f"expected group {GROUP}, got {groups}")
    print(f"Dashboard user is {EMAIL}, groups are {groups}")
    print(f"Session cookie size: {len(session_cookie(session))} bytes")


def check_applications(session):
    failures = []
    for application, path in APPLICATION_ENDPOINTS.items():
        own = session.get(
            KUBEFLOW_URL + path.format(namespace=NAMESPACE), timeout=TIMEOUT
        )
        other = session.get(
            KUBEFLOW_URL + path.format(namespace="kubeflow"), timeout=TIMEOUT
        )
        print(
            f"{application}: {NAMESPACE} -> {own.status_code}, kubeflow -> {other.status_code}"
        )
        if own.status_code != 200:
            failures.append(
                f"{application} {NAMESPACE}: {own.status_code} {own.text[:200]}"
            )
        if other.status_code not in (401, 403):
            failures.append(
                f"{application} kubeflow: {other.status_code} {other.text[:200]}"
            )
    if failures:
        raise RuntimeError("; ".join(failures))
    print("All web applications accept the Keycloak user and enforce namespace access")


def check_refresh(session):
    cookie = session_cookie(session)
    print(f"Waiting {TOKEN_LIFESPAN_SECONDS + 30}s for the ID token to expire ...")
    time.sleep(TOKEN_LIFESPAN_SECONDS + 30)
    check_dashboard_user(session)
    if session_cookie(session) == cookie:
        raise RuntimeError(
            "request worked, but the browser never got the refreshed cookie"
        )
    print("Session refreshed after the ID token expired")
    check_applications(session)


def main():
    check_keycloak_rejects_dex_settings()
    session = login()
    check_claims(session)
    check_applications(session)
    check_refresh(session)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Keycloak login test failed: {error}", file=sys.stderr)
        sys.exit(1)
