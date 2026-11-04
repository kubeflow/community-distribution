#!/usr/bin/env python3
# Logs in to Kubeflow through OAuth2 Proxy and Dex, waits for the ID token to
# expire and verifies that the session is refreshed: concurrent requests with
# the previous session cookie all succeed, the browser receives the refreshed
# cookie through Istio, and the previous refresh token is refused once the
# reuse interval has passed.
# Setup: the step "Shorten the token lifetimes for the session refresh test" in
# .github/workflows/dex_oauth2-proxy_test.yaml

import concurrent.futures
import sys
import time

import requests

from dex_login_test import DexSessionManager

KUBEFLOW_URL = "http://localhost:8080"
# cookie_name in common/oauth2-proxy/base/oauth2_proxy.cfg. OAuth2 Proxy splits a
# large session cookie into numbered parts with this prefix.
COOKIE_NAME = "oauth2_proxy_kubeflow"
DEX_USERNAME = "user@example.com"
DEX_PASSWORD = "12341234"
# expiry.idTokens, shortened from one hour by the workflow step
ID_TOKEN_LIFETIME_SECONDS = 60
# expiry.refreshTokens.reuseInterval in common/dex/base/config-map.yaml
REFRESH_TOKEN_REUSE_SECONDS = 60
# A dashboard page load fans out into several requests at once; every one of
# them carries the previous session cookie until the first refreshed answer
# arrives, and each OAuth2 Proxy replica refreshes on its own.
PARALLEL_REQUESTS = 8
TIMEOUT = 15
# The dashboard answers with the user Istio took from the ID token, so a 200
# proves that the token in the Authorization header is valid.
DASHBOARD_USER_PATH = "/api/workgroup/env-info"


def session_cookie(cookies):
    """The session cookie parts, by name, out of a list of cookies."""
    return {
        cookie.name: cookie.value
        for cookie in cookies
        if cookie.name.startswith(COOKIE_NAME)
    }


def cookie_header(session_cookie):
    return "; ".join(
        f"{name}={value}" for name, value in sorted(session_cookie.items())
    )


def login():
    # The cookies come back as "name=value; name=value", like a Cookie header.
    cookies = DexSessionManager(
        endpoint_url=KUBEFLOW_URL,
        dex_username=DEX_USERNAME,
        dex_password=DEX_PASSWORD,
    ).get_session_cookies()
    previous_cookie = {
        name: value
        for name, value in (part.split("=", 1) for part in cookies.split("; "))
        if name.startswith(COOKIE_NAME)
    }
    if not previous_cookie:
        raise RuntimeError(f"no {COOKIE_NAME} cookie after the login: {cookies}")
    print("Logged in through OAuth2 Proxy and Dex")
    return previous_cookie


def dashboard_user(session_cookie_parts):
    """Status, user and the session cookie the answer set, if any. The cookie
    is sent as a header, because the cookie jar does not match a cookie without
    a dot in its domain against localhost."""
    response = requests.get(
        KUBEFLOW_URL + DASHBOARD_USER_PATH,
        headers={"Cookie": cookie_header(session_cookie_parts)},
        allow_redirects=False,
        timeout=TIMEOUT,
    )
    user = response.json().get("user") if response.status_code == 200 else None
    return response.status_code, user, session_cookie(response.cookies)


def check_dashboard_user(session_cookie_parts):
    status, user, _ = dashboard_user(session_cookie_parts)
    if status != 200 or user != DEX_USERNAME:
        raise RuntimeError(f"dashboard: {status} {user}")


def check_concurrent_refresh(previous_cookie):
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=PARALLEL_REQUESTS
    ) as executor:
        results = list(
            executor.map(dashboard_user, [previous_cookie] * PARALLEL_REQUESTS)
        )
    failures = [
        f"{status} {user}"
        for status, user, _ in results
        if status != 200 or user != DEX_USERNAME
    ]
    if failures:
        raise RuntimeError(
            f"{len(failures)} of {PARALLEL_REQUESTS} concurrent requests with the "
            f"expired ID token failed: {failures}"
        )
    refreshed_cookies = [
        cookie for _, _, cookie in results if cookie and cookie != previous_cookie
    ]
    if len(refreshed_cookies) != PARALLEL_REQUESTS:
        raise RuntimeError(
            f"only {len(refreshed_cookies)} of {PARALLEL_REQUESTS} responses carried "
            "a refreshed session cookie"
        )
    print(
        f"{PARALLEL_REQUESTS} concurrent requests refreshed the session, "
        f"{len(refreshed_cookies)} refreshed cookies returned"
    )
    return refreshed_cookies[0]


def main():
    previous_cookie = login()
    check_dashboard_user(previous_cookie)

    print(f"Waiting {ID_TOKEN_LIFETIME_SECONDS + 30}s for the ID token to expire ...")
    time.sleep(ID_TOKEN_LIFETIME_SECONDS + 30)
    refreshed_cookie = check_concurrent_refresh(previous_cookie)
    check_dashboard_user(refreshed_cookie)
    print("The refreshed cookie opens the dashboard")

    print(f"Waiting {REFRESH_TOKEN_REUSE_SECONDS + 5}s for the reuse interval ...")
    time.sleep(REFRESH_TOKEN_REUSE_SECONDS + 5)
    status, user, _ = dashboard_user(previous_cookie)
    if status != 401:
        raise RuntimeError(
            f"the previous refresh token was still accepted: {status} {user}"
        )
    print("The previous refresh token is refused after the reuse interval")
    check_dashboard_user(refreshed_cookie)
    print("The refreshed session is still open")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Dex session refresh test failed: {error}", file=sys.stderr)
        sys.exit(1)
