# Kubeflow Dex & Keycloak Integration Guide

In addition to the guidelines for GitHub, Google, Microsoft and other OIDC providers in https://github.com/kubeflow/community-distribution#dex and direct oauth2-proxy connection without DEX to typical OIDC IDP providers such as Azure in https://github.com/kubeflow/community-distribution/blob/master/common/oauth2-proxy/README.md#change-the-default-authentication-from-dex--oauth2-proxy-to-oauth2-proxy-only we try to roughly explain here how to configure Dex to use Keycloak as an external OpenID Connect provider for Kubeflow.

> [Note]
> ✅ Replace the domains of Keycloak and Kubeflow containing `example.com` with ones that are appropriately tailored to the actual situation.
> ✅ If a realm already exists, there's no need to create one.
> ✅ As you know, If the first attempt fails, you can just run it again.

## Connect OAuth2 Proxy directly to Keycloak, without Dex

Keycloak is a complete OpenID Connect provider, so Dex is not required between OAuth2 Proxy and Keycloak. This section describes that setup. It keeps the default Kubeflow authentication flow: OAuth2 Proxy checks every browser request as the Istio external authorization provider, places the Keycloak ID token in the `Authorization` header, and the Istio `RequestAuthentication` verifies that token and sets the `kubeflow-userid` and `kubeflow-groups` headers. Only the issuer changes from Dex to Keycloak.

The sections after this one describe the alternative setup with Dex between OAuth2 Proxy and Keycloak.

The [Keycloak integration workflow](../../.github/workflows/keycloak_oauth2-proxy_test.yaml) uses the [test configuration](../../tests/keycloak/) to verify login, claims, namespace access and session refresh. It also runs the existing Workspaces service account access test. The test uses local HTTP and shorter token lifetimes; the example below uses HTTPS and the default Keycloak token lifetime.

### Create the Keycloak client

In your realm, create a client with these settings:

- Client type: `OpenID Connect`
- Client ID: any value, for example `kubeflow`. The fixed client identifier `kubeflow-oidc-authservice` is only required by the Dex configuration.
- Client authentication: `On`
- Authentication flow: `Standard flow` only
- Valid redirect URIs: `https://kubeflow.example.com/oauth2/callback`
- Web origins: `https://kubeflow.example.com`
- Proof Key for Code Exchange method (under Advanced): `S256`, because OAuth2 Proxy sends `code_challenge_method = "S256"`

Note the client secret from the Credentials tab.

### Prepare the claims Kubeflow uses

- **Email:** Kubeflow identifies a user by the `email` claim, which Istio copies into the `kubeflow-userid` header. Every user must have an email address that is marked as verified, because OAuth2 Proxy rejects unverified addresses. For users who log in through an identity provider brokered by Keycloak, enable `Trust Email` on that identity provider. The `spec.owner.name` field of each Kubeflow Profile must match this email address exactly.
- **Groups (optional):** Keycloak does not include group membership in its tokens by default. To fill the `kubeflow-groups` header, add a `Group Membership` mapper to the dedicated scope of the client, with token claim name `groups`, `Full group path` set to `Off`, and `Add to ID token` set to `On`. Do not request a scope named `groups`: Keycloak has no client scope with that name and rejects the login request with `invalid_scope`.

### Configure OAuth2 Proxy

Create an overlay that replaces the OAuth2 Proxy configuration file and Secret. Never change `common/oauth2-proxy/base` directly.

This example uses `m2m-dex-and-kind`, matching the integration test and preserving Kubernetes service account access on KinD. For another Kubernetes distribution, use the corresponding machine-to-machine overlay, such as `m2m-dex-and-eks`, instead.

```yaml
# overlays/keycloak/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- ../../common/oauth2-proxy/overlays/m2m-dex-and-kind

configMapGenerator:
- name: oauth2-proxy
  behavior: replace
  files:
  - oauth2_proxy.cfg
- name: oauth2-proxy-parameters
  behavior: merge
  literals:
  - FORCE_HTTPS=true
  # Set to true only if the Keycloak certificate is not trusted by the OAuth2 Proxy image.
  - ALLOW_SELF_SIGNED_ISSUER=false

secretGenerator:
- name: oauth2-proxy
  behavior: replace
  # Contains client-id, client-secret and cookie-secret.
  # Create this file from your secret manager and never commit it.
  envs:
  - oauth2-proxy.env

patches:
- target:
    kind: RequestAuthentication
    name: dex-jwt
  patch: |-
    - op: replace
      path: /spec/jwtRules/0/issuer
      value: https://keycloak.example.com/realms/<my-realm>
```

The `oauth2_proxy.cfg` file in the overlay is based on `common/oauth2-proxy/base/oauth2_proxy.cfg`. It removes the Dex-specific settings: OpenID Connect discovery is enabled again, so `skip_oidc_discovery`, `login_url`, `redeem_url` and `oidc_jwks_url` are removed, `prompt = "none"` is removed because Keycloak answers it with `login_required` when the user has no session yet, and `redirect_url` is an absolute address with `relative_redirect_url = false`, because Keycloak rejects the relative redirect address that Dex accepts with HTTP status 400.

```toml
provider = "oidc"
oidc_issuer_url = "https://keycloak.example.com/realms/<my-realm>"
scope = "openid profile email"
email_domains = [ "*" ]

upstreams = [ "static://200" ]

api_routes = [
  "/api/",
  "/apis/",
  "^/ml_metadata",
]

skip_provider_button = false
provider_display_name = "Keycloak"
custom_sign_in_logo = "/custom-theme/kubeflow-logo.svg"
banner = "-"
footer = "-"

set_authorization_header = true
set_xauthrequest = true

cookie_name = "oauth2_proxy_kubeflow"
# Keycloak issues ID tokens that expire after 5 minutes by default (realm setting
# "Access Token Lifespan"), while Dex issues them for 24 hours. Istio rejects an
# expired token, so OAuth2 Proxy must refresh the session before the token expires.
cookie_refresh = "4m"
# Keep this at or below the realm setting "SSO Session Max" (10 hours by default),
# after which Keycloak refuses to refresh the session.
cookie_expire = "10h"

code_challenge_method = "S256"

redirect_url = "https://kubeflow.example.com/oauth2/callback"
relative_redirect_url = false
```

The issuer must be identical in three places: the `iss` claim that Keycloak writes into its tokens (derived from the Keycloak hostname configuration), `oidc_issuer_url` in OAuth2 Proxy, and the issuer of the `RequestAuthentication`. OAuth2 Proxy and istiod both fetch the issuer discovery document and signing keys, so both must be able to reach that address. If istiod cannot reach the public Keycloak address or does not trust its certificate, add `jwksUri` with an address istiod can reach, for example `http://keycloak.keycloak.svc.cluster.local:8080/realms/<my-realm>/protocol/openid-connect/certs`.

Apply the overlay:

```bash
kustomize build overlays/keycloak | kubectl apply -f -
```

### Let Istio return the refreshed session cookie

When OAuth2 Proxy refreshes the session, it sends the new session cookie in its answer to the Istio external authorization check. The default Istio configuration in `common/oauth2-proxy/components/istio-external-auth-patches/patches/cm.enable-oauth2-proxy.yaml` only forwards `set-cookie` to the browser on denied requests (`headersToDownstreamOnDeny`). With Dex this does not matter, because the Dex tokens are valid for 24 hours and `cookie_refresh = 0` disables the refresh. With Keycloak, the browser keeps the original session cookie, so the refreshed tokens are never stored and every later request depends on the original refresh token. Add `set-cookie` to `headersToDownstreamOnAllow` of the `oauth2-proxy` extension provider in the `istio` ConfigMap of the `istio-system` namespace:

```yaml
extensionProviders:
- name: oauth2-proxy
  envoyExtAuthzHttp:
    service: oauth2-proxy.oauth2-proxy.svc.cluster.local
    port: 80
    headersToDownstreamOnAllow:
    - set-cookie
    headersToDownstreamOnDeny:
    - content-type
    - set-cookie
    headersToUpstreamOnAllow:
    - authorization
    - path
    - x-auth-request-email
    - x-auth-request-groups
    - x-auth-request-user
    includeRequestHeadersInCheck:
    - authorization
    - cookie
```

### Known issues without Dex

- **Large cookies:** The OAuth2 Proxy cookie stores the ID token, the access token and the refresh token. A minimal Keycloak realm produces a cookie of about 3.5 kilobytes, but many groups, roles or custom claims can push it beyond 8 kilobytes. Several Kubeflow web applications then answer with HTTP status 431 (Request Header Fields Too Large). Store the session in Redis with `session_store_type = "redis"` so that the cookie only holds a session ticket, or apply the web application changes in the Known Issues section of [common/oauth2-proxy/README.md](../oauth2-proxy/README.md).
- **Machine-to-machine access:** The `m2m-dex-and-kind` overlay above retains Kubernetes service account token validation for KinD. Other Kubernetes distributions require the corresponding machine-to-machine overlay; `m2m-dex-only` does not provide Kubernetes service account token validation. See [common/oauth2-proxy/README.md](../oauth2-proxy/README.md) for the available overlays. Keycloak client credentials tokens are not covered here: these tokens contain no email claim unless you configure one, so these tokens do not produce a `kubeflow-userid` header.

## Configure Keycloak

### Create a Realm

- Realm Name: `<my-realm>`

### Create a Client
- Client Type: `OpenID Connect`
- Client ID: `kubeflow-oidc-authservice` (⚠️ Never use a different value)
- Client Authentication: `On`
- Authentication Flow: Check `Standard flow` and `Direct access grants`
- Root URL: `https://kubeflow.example.com`
- Home URL: `https://kubeflow.example.com`
- Valid Redirect URIs: `https://kubeflow.example.com/dex/callback`
- Valid Post Logout Redirect URIs: `https://kubeflow.example.com/oauth2/sign_out`
- Web Origins: `*`

After creating the realm and client, note down the **Client Secret**(`YOUR_KEYCLOAK_CLIENT_SECRET`) which will be used in later steps.

## Update Dex Configuration

Modify the Dex ConfigMap to connect to Keycloak.

```bash
KEYCLOAK_ISSUER="https://keycloak.example.com/realms/<my-realm>"
# INTERNAL Keycloak (running inside the Kubernetes cluster)
KEYCLOAK_JWKS_URI="http://keycloak.auth.svc.cluster.local:8080/realms/<my-realm>/protocol/openid-connect/certs"
# If Keycloak is external:
#KEYCLOAK_JWKS_URI="https://keycloak.example.com/realms/<my-realm>/protocol/openid-connect/certs"
CLIENT_ID="kubeflow-oidc-authservice"
CLIENT_SECRET="<YOUR_KEYCLOAK_CLIENT_SECRET>"
REDIRECT_URI="https://kubeflow.example.com/dex/callback"
DEX_ISSUER="https://kubeflow.example.com/dex"


tee common/dex/overlays/oauth2-proxy/config-map.yaml <<- DEX_CONFIG
apiVersion: v1
kind: ConfigMap
metadata:
  name: dex
data:
  config.yaml: |
    issuer: $DEX_ISSUER
    storage:
      type: kubernetes
      config:
        inCluster: true
    web:
      http: 0.0.0.0:5556
    logger:
      level: "debug"
      format: text
    oauth2:
      skipApprovalScreen: true
    enablePasswordDB: false
    # staticPasswords:
    # - email: user@example.com
    #   hashFromEnv: DEX_USER_PASSWORD
    #   username: user
    #   userID: "15841185641784"
    staticClients:
    - idEnv: OIDC_CLIENT_ID
      redirectURIs: ["/oauth2/callback"]
      name: 'Dex Login Application'
      secretEnv: OIDC_CLIENT_SECRET
    connectors:
    - type: oidc
      id: keycloak
      name: keycloak
      config:
        issuer: $KEYCLOAK_ISSUER

        # Override JWKS endpoint: Dex will fetch Keycloak's JWKs from here.
        # This is useful when issuer discovery fails or when the IdP uses
        # self-signed / internal-only certificates.
        # Keycloak's endpoint /realms/{realm}/protocol/openid-connect/certs. See the Keycloak documentation here https://www.keycloak.org/docs/latest/securing_apps/index.html#certificate-endpoint
        jwksUri: $KEYCLOAK_JWKS_URI
        clientID: $CLIENT_ID
        clientSecret: $CLIENT_SECRET
        redirectURI: $REDIRECT_URI
        insecureSkipVerify: true
        # Disable TLS certificate verification when connecting to the issuer.
        # This is required for test or on-premises installations using self-signed
        # certificates.
        # Dex does not support an `insecure` field. TLS verification is controlled
        # via `insecureSkipVerify`, which is implemented in the Dex OIDC connector.
        # Source: https://github.com/dexidp/dex/blob/master/connector/oidc/oidc.go
        insecureSkipEmailVerified: true
        userNameKey: email
        scopes:
          - openid
          - profile
          - email
          - offline_access
DEX_CONFIG


kustomize build common/dex/overlays/oauth2-proxy | kubectl delete -f -
kustomize build common/dex/overlays/oauth2-proxy | kubectl apply -f -
```

## Update OAuth2 Proxy Configuration
Configure the OAuth2 Proxy to use the newly configured Dex issuer.

```bash
DEX_ISSUER="https://kubeflow.example.com/dex"

tee common/oauth2-proxy/base/oauth2_proxy.cfg <<- OAUTH2_PROXY_CONFIG
provider = "oidc"
oidc_issuer_url = "$DEX_ISSUER"
scope = "profile email offline_access openid"
email_domains = "*"
insecure_oidc_allow_unverified_email = "true"

upstreams = [ "static://200" ]

skip_auth_routes = [
  "^/dex/",
]

api_routes = [
  "/api/",
  "/apis/",
  "^/ml_metadata",
]

skip_oidc_discovery = true
login_url = "/dex/auth"
redeem_url = "http://dex.auth.svc.cluster.local:5556/dex/token"
oidc_jwks_url = "http://dex.auth.svc.cluster.local:5556/dex/keys"

skip_provider_button = false

provider_display_name = "Dex"
custom_sign_in_logo = "/custom-theme/kubeflow-logo.svg"
banner = "-"
footer = "-"

prompt = "none"

set_authorization_header = true
set_xauthrequest = true

cookie_name = "oauth2_proxy_kubeflow"
cookie_expire = "24h"
cookie_refresh = 0

code_challenge_method = "S256"

redirect_url = "/oauth2/callback"
relative_redirect_url = true
OAUTH2_PROXY_CONFIG


kustomize build common/oauth2-proxy/overlays/m2m-dex-only/ | kubectl delete -f -
kustomize build common/oauth2-proxy/overlays/m2m-dex-only/ | kubectl apply -f -
```

## Update Istio Request Authentication
Adjust the Istio Request Authentication configuration to pass the correct JWT claims.

```bash
DEX_ISSUER="https://kubeflow.example.com/dex"

tee common/oauth2-proxy/components/istio-external-auth/requestauthentication.dex-jwt.yaml <<- ISTIO_REQUEST_AUTH_CONFIG
apiVersion: security.istio.io/v1beta1
kind: RequestAuthentication
metadata:
  name: dex-jwt
  namespace: istio-system
spec:
  selector:
    matchLabels:
      app: istio-ingressgateway
  jwtRules:
  - issuer: $DEX_ISSUER
    forwardOriginalToken: true
    outputClaimToHeaders:
    - header: kubeflow-userid
      claim: email
    - header: kubeflow-groups
      claim: groups
    fromHeaders:
    - name: Authorization
      prefix: "Bearer "
ISTIO_REQUEST_AUTH_CONFIG

kustomize build common/istio/istio-install/overlays/oauth2-proxy | kubectl delete -f -
kustomize build common/istio/istio-install/overlays/oauth2-proxy | kubectl apply -f -
kustomize build common/oauth2-proxy/overlays/m2m-dex-only/ | kubectl delete -f -
kustomize build common/oauth2-proxy/overlays/m2m-dex-only/ | kubectl apply -f -
```

## Final Checks
- **Review Logs**: Make sure to tail the logs of the Dex, OAuth2 Proxy, and Istio ingress gateway deployments to verify that the configurations are working as expected.
- **Test Authentication**: Try accessing your Kubeflow endpoint (ex. https://kubeflow.example.com) and verify that you’re redirected to Keycloak for authentication and that after login you are correctly returned to Kubeflow.

---

# Known issues

- Microsoft Azure deployment with AD groups authentication: having a large number of AD groups assigned to a user may lead to Dex authentication issues with HTTP 4xx/5xx responses. To fix this - make the authentication more precise with the whitelisting of the groups. [Documentation reference](https://dexidp.io/docs/connectors/microsoft/#:~:text=%2D%20email-,Groups,-When%20the%20groups)

Dex configMap example:

```yaml
"connectors" = [
  {
    "type" = "microsoft"
    "id"   = "microsoft"
    "name" = "Microsoft"
    "config" = {
      "clientID"             = "$${DEX_MICROSOFT_CLIENT_ID}"
      "clientSecret"         = "$${DEX_MICROSOFT_CLIENT_SECRET}"
      "redirectURI"          = "https://kubeflow.example.com/dex/callback"
      "tenant"               = "$${DEX_MICROSOFT_TENANT_ID}"

      "emailToLowercase"     = true (optional but should be always used)
      "groups"               = "<AD groups>"
      "onlySecurityGroups"   = true (optional, AD groups may have different assignments)
      "useGroupsAsWhitelist" = true
    }
  }
]
```
---
