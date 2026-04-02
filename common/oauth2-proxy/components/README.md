# Kubeflow with oauth2-proxy and envoyExtAuthzHttp

For a quick install, see [Example installation](#example-installation).


## Description

Kubeflow authorization operates using custom authentication headers:
* `kubeflow-userid`: Contains the user's email address.
* `kubeflow-groups`: Holds a comma-separated list of user groups.
    * Note: The functionality for `kubeflow-groups` is not fully operational at this time.

This feature was implemented using a custom, minimalistic authorization tool from Arrikto
named `oidc-authservice`. This tool was integrated into Istio using `EnvoyFilter`.

The adoption of `envoyExtAuthzHttp` for authentication offers several advantages:
* **Simplified Authorization Process**: `envoyExtAuthzHttp` extension streamlines adding
  external authorization to the Envoy proxy within an Istio service mesh. It allows for
  declarative policy configuration, reducing the complexity associated with direct
  `EnvoyFilter` modifications.
* **Standardization**: Istio recommends `envoyExtAuthzHttp` for its standardized approach.
  This promotes consistency across Istio deployments and simplifies understanding and
  maintenance of the authorization logic.
* **Separate Policy Management**: Authorization policies are defined in distinct
  configuration resources, not directly in `EnvoyFilter`. This separation eases policy
  management and facilitates updates or replacements of authorization logic without
  altering `EnvoyFilter` configurations.
* **Seamless Integration with Istio**: `envoyExtAuthzHttp` harmonizes with Istio features
  like `AuthorizationPolicy` and `VirtualService`, enabling smoother integration within
  Istio's ecosystem and taking advantage of its architecture and capabilities.
* **Future-Proofing**: There is a high likelihood that Kubeflow's internal authentication
  decisions will transition to relying directly on JWTs instead of custom auth headers.

Additional information on the benefits of moving away from `EnvoyFilter` can be found in these
resources:
* [Istio GitHub Issue #27790](https://github.com/istio/istio/issues/27790)
* [Istio Documentation on Authorization with Custom Authentication](https://istio.io/latest/docs/tasks/security/authorization/authz-custom/)

While `envoyExtAuthzHttp` could potentially integrate with `oidc-authservice`, `oauth2-proxy`
emerges as a more advanced authentication proxy. It boasts broader community support and is
widely used in the industry, including in the official Istio documentation on [External
Authorization](https://istio.io/latest/docs/tasks/security/authorization/authz-custom).

For more details on the `oauth2-proxy`, refer to the [official documentation](https://oauth2-proxy.github.io/oauth2-proxy/docs/behaviour).

## Available Components

Below is a list of the available Kustomize Components with brief descriptions. Click on each for more details.

* **[allow-unauthenticated-issuer-discovery](./allow-unauthenticated-issuer-discovery.md)** -
  Creates a ClusterRoleBinding for anonymous access to Kubernetes OIDC
  discovery.

* **[central-dashboard](./central-dashboard.md)** - Configures the central
  dashboard to use oauth2-proxy logout URL.

* **[istio-external-auth](./istio-external-auth.md)** - Modifies Istio
  configuration to define oauth2-proxy as external authentication middleware via
  envoyExtAuthzHttp extension provider. Adds RequestAuthentication to trust Dex
  as IdP and AuthorizationPolicies to delegate authentication to oauth2-proxy.

* **[istio-m2m](./istio-m2m.md)** - Creates RequestAuthentication for Istio to
  trust the OIDC Issuer specified in parameters. This allows the generation of
  JWTs for authenticating requests, typically as Bearer Tokens in the
  Authorization header. By default, the OIDC Issuer is the in-cluster Kubernetes
  OIDC.

## CloudFlare

CloudFlare requires that certain static, standard web browser assets are accessible without
user authentication. This is crucial because CloudFlare aims to cache these assets for
enhanced performance. If these assets necessitate user authentication, CloudFlare robots
will be redirected to the authentication page, potentially causing access issues with the
Kubeflow instance behind CloudFlare.

This issue can be resolved by defining a set of assets in the Istio `AuthorizationPolicy`
that do not require authentication. An example `AuthorizationPolicy` for this purpose is
provided in the file `authorizationpolicy.istio-ingressgateway-oauth2-proxy.cloudflare.yaml`.

## Explaining the Auth Routine

1. Istio is configured with the `envoyExtAuthzHttp` extension provider pointing to the
   `oauth2-proxy` service. This configuration enables the use of this extension in
   `AuthorizationPolicy` for adding external authorization to the service mesh.
2. The Istio service mesh has an `AuthorizationPolicy` named `istio-ingressgateway-oauth2-proxy`
   in the `istio-system` (Istio root) namespace. This policy is set with `action: CUSTOM` and
   specifies the `oauth2-proxy` provider. Consequently, every request to the
   `istio-ingressgateway` must pass through the external authorization service, `oauth2-proxy`.
3. `oauth2-proxy` decides based on the cookie named `oauth2_proxy_kubeflow`. If this cookie
   is absent, expired, or invalid, `oauth2-proxy` redirects to the configured OIDC provider,
   typically `dex`. The authentication redirect includes:
    * A `redirect_uri` for redirecting the user post-authentication,
    * A code challenge to guard against interception and replay attacks,
    * A state parameter to validate the authorization response's authenticity and
      ensure it originates from the initial request.

   Post-authentication, a cookie is set in the user's browser, used by Istio and `oauth2-proxy`
   for authorizing requests.

   `oauth2-proxy` also checks for an `Authorization` header with a JWT bearer token. It trusts
   JWTs issued by the configured OIDC provider (default `dex`) and can be configured to trust
   additional JWTs. If a valid JWT is present, `oauth2-proxy` forwards the request to Istio
   along with the authorization header.

   The key objective here is to supply an `Authorization` header with a JWT Bearer Token,
   later used in `RequestAuthentication`. This step configures Istio to trust the JWT, parse
   its claims to include user email and groups in custom Kubeflow authorization headers, and
   make routing and authorization decisions based on these JWT claims.
4. With this setup, Istio always receives the JWT in requests, enabling authorization
   decisions based on JWT claims.

## Using HTTPS

`oauth2-proxy` is initially set up with an `http` endpoint, secured by the Istio Service Mesh.
As a result, `oauth2-proxy` may default to assuming that the authentication redirect URI should
also use `http`. To enforce the use of `https`, modify the variable `FORCE_HTTPS` in
`kustomization.yaml` to `true`. This adjustment leverages the `oauth2-proxy` configuration
option `--cookie-secure`, ensuring redirection occurs with `https`.

## Istio JWT Public Key Refresh Interval

In the initial setup of Kubeflow, it's common for `istiod` to become available before `dex`.
Istio's `RequestAuthentication` is configured to retrieve the JWT Public Key from the Issuer
URL. If the Issuer is not yet operational, placeholder keys are set, which can render the
setup nonfunctional until Istio can access the correct JWT Public Key. To address this,
`istiod` is configured with the environment variable `PILOT_JWT_PUB_KEY_REFRESH_INTERVAL="1m"`.
This setting ensures the JWT Public Key is refreshed every minute, rather than the default
20 minutes.

Without this configuration, users may encounter the following Istio error:
```
Jwks doesn't have key to match kid or alg from Jwt
```

## Issues with This Setup

While not an inherent issue with Istio or `oauth2-proxy`, the current Kubeflow configuration
automatically redirects to a URL specified in the logout response body's `afterLogoutURL` key.
This behavior stems from custom integration with the `oidc-authservice` component. While
`oauth2-proxy` is capable of redirecting to the base Kubeflow page, this custom setup results
in users being logged out (with the authentication cookie removed) but not redirected back to
the Kubeflow Home Page.

Details of this custom integration are available at:
* [oidc-authservice server.go](https://github.com/arrikto/oidc-authservice/blob/0c4ea9a/server.go#L509)
* [Kubeflow logout-button.js](https://github.com/kubeflow/kubeflow/blob/c6c4492/components/centraldashboard/public/components/logout-button.js#L50)

To log in again, users must manually refresh the page.

## Example Installation

To install Kubeflow configured to use `oauth2-proxy` with Istio's `envoyExtAuthzHttp` extension,
make the following changes to the `example/kustomization.yaml` file:
* use `oauth2-proxy` overlay for istio-install
  ```
  # from
  - ../common/istio/istio-install/base
  # to
  - ../common/istio/istio-install/overlays/oauth2-proxy
  ```
* change `OIDC Authservice` to `oauth2-proxy for OIDC` and use overlay for m2m
  bearer tokens with self-signed in-cluster issuer
  ```
  # from
  - ../common//oidc-authservice/base
  # to
  - ../common/oauth2-proxy/overlays/m2m-dex-and-kind
  ```
* change Dex overlay
  ```
  # from
  - ../common/dex/overlays/istio
  # to
  - ../common/dex/overlays/oauth2-proxy
