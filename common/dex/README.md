# Kubeflow Dex & Keycloak Integration Guide

In addition to the guidelines for GitHub, Google, Microsoft and other OIDC providers in https://github.com/kubeflow/community-distribution#dex and direct oauth2-proxy connection without DEX to typical OIDC IDP providers such as Azure in https://github.com/kubeflow/community-distribution/blob/master/common/oauth2-proxy/README.md#change-the-default-authentication-from-dex--oauth2-proxy-to-oauth2-proxy-only we try to roughly explain here how to configure Dex to use Keycloak as an external OpenID Connect provider for Kubeflow.

> [Note]
> ✅ Replace the domains of Keycloak and Kubeflow containing `example.com` with ones that are appropriately tailored to the actual situation.
> ✅ If a realm already exists, there's no need to create one.
> ✅ As you know, If the first attempt fails, you can just run it again.

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
