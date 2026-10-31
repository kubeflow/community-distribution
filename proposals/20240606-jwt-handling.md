# Standardise JWT Usage

**Authors**: Kimonas Sotirchos @kimwnasptd

## Requirements
- OIDC logic, via the [Istio external authoriser](https://istio.io/latest/docs/tasks/security/authorization/authz-custom/), should add `id_token` to HTTP requests in `Authorization: Bearer <token>` headers
## Scope
This proposal aims to standardise how Kubeflow backends handle user information (the username and group memberships) stored in JWTs and HTTP headers.

This proposal requires that users can use Kubernetes tokens in `Authorization: Bearer <token>` headers in requests from inside the cluster. The issuer of the tokens should not be relevant to Kubeflow applications. The service mesh will verify the tokens and support multiple issuers, such as Dex and Kubernetes. The applications will use only the user and group information from the tokens.
### In
- Which component should validate JWTs (OIDC ID tokens or Kubernetes ServiceAccount tokens)
- Define where the backends should expect to find user related information
- Define how different token issuers, such as Dex and Kubernetes, should be handled
### Out
- Proposing code changes to existing components
## Current State
As of Kubeflow 1.8, user information is injected into requests as the `kubeflow-userid` header by the AuthService (replaced by `oauth2-proxy`). Kubeflow follows these patterns to secure this approach:
1. Backends in the `kubeflow` namespace that need to know the user identity rely on `kubeflow-userid` headers in HTTP requests.
2. The AuthService adds the `kubeflow-userid` header to all authenticated requests.
3. Only requests from the Istio IngressGateway are trusted to have the `kubeflow-userid` header
    1. Backends that are not exposed to user namespaces, such as `jupyter-web-app`, are only reachable via the Istio IngressGateway.
    2. The KFP backend [explicitly drops requests](https://github.com/kubeflow/community-distribution/blob/96ce068e16b2a707464471bddc0d2a58e403d1fc/apps/pipeline/upstream/base/installs/multi-user/istio-authorization-config.yaml#L37) from user namespaces if they have this header
    3. In-cluster Pods that need to communicate with identity-aware `kubeflow` workloads [use a Kubernetes ServiceAccount token](https://www.kubeflow.org/docs/components/pipelines/v1/sdk/connect-api/#full-kubeflow-subfrom-inside-clustersub)
### Limitations
- Not able to express `AuthorizationPolicies` for group header in Istio
- Limited possibility to use custom JWT claims as a source of information about the authenticated user

To accommodate the above limitations and improve the authentication and authorization flow in terms of security, maintenance and flexibility
we propose to add the JWT to the `Authorization` header, so it can be digested by Istio and have the user details securely
injected into the `Authorization` headers. This will also enable us to define policies in the future for better handling of groups.
https://istio.io/latest/docs/tasks/security/authorization/authz-jwt/

However, the following topics require agreement:
1. The platform will need to handle `id_tokens` from different issuers, such as Dex and Kubernetes
2. User information is present in both `kubeflow-userid` and the HTTP request's `id_token`, so Kubeflow components need an agreed source of identity
3. It is not clear whether backends should validate the JWT; KFP currently validates ServiceAccount tokens ([`1`](https://github.com/kubeflow/pipelines/blob/2.2.0/backend/src/apiserver/auth/authenticator_token_review.go#L47-L58), [`2`](https://github.com/kubeflow/pipelines/blob/2.2.0/backend/src/apiserver/resource/resource_manager.go#L1698-L1699))

## Specification
The goal of this proposal is to provide a uniform way for all backends to handle identity tokens and to specify
which levels of the stack are responsible for which parts.

This specification proposes the following high-level agreement for new backends:
1. Requests to `kubeflow` applications that expect user identity should have a JWT in the `Authorization: Bearer <token>` header
2. The service mesh is responsible for validating the JWTs
    1. The service mesh must reject a request with HTTP 401 if the JWT is invalid (`RequestAuthentication`)
    2. The service mesh must reject a request with HTTP 403 if the JWT is absent and the application expects requests to have a user identity (`AuthorizationPolicy`)
3. The backends are not responsible for validating the JWTs or their existence
4. The service mesh must expose user and group information in the `kubeflow-userid` and `kubeflow-groups` headers after validating JWTs
    1. if the mesh will not override these headers, then users could forge requests and impersonate other users by setting the header and any valid token
    1. for User to Machine traffic, the `email` claim from `id_token` should be used by default but it should also allow parameterization to allow using different claims. This is doable via `RequestAuthentication` with object per issuer
    2. For Kubernetes ServiceAccount tokens, the `sub` claim will be used. Its format is `system:serviceaccount:<sa-namespace>:<sa-name>`
    3. in case of Dex tokens it would be `kimonas@email.com`
5. The backends will use the information from the headers and not deal with JWTs
    1. `SubjectAccessReviews` should be made for the `user` and `groups` that were exposed from the headers, independently of the issuer of the token
    2. [`SubjectAccessReview API`](https://kubernetes.io/docs/reference/kubernetes-api/authorization-resources/subject-access-review-v1/) uses the `user`,
       `groups`, `resource`, and `verb` details to verify access against Kubernetes RBAC, which allows authorization for specific actions based on
       the standard Kubernetes RBAC implementation

With this implementation, all JWT-handling logic moves to the service mesh, leaving only business logic in the applications. The applications do not need to distinguish token types, such as Dex and Kubernetes tokens, and only need to read the corresponding headers.

This proposal aims to put more focus on keeping and validating `id_tokens` but also bridging to the existing functionality of the backends, to avoid extensive changes.
### Implementation
The technical details for the above proposal translate to the following
1. Common Kubeflow manifests, for all components, for configuring Istio for supporting multiple issuers ([Dex](https://github.com/kubeflow/community-distribution/blob/v1.9-branch/common/oauth2-proxy/components/istio-external-auth/requestauthentication.dex-jwt.yaml) and [Kubernetes machine-to-machine](https://github.com/kubeflow/community-distribution/blob/v1.9-branch/common/oauth2-proxy/components/istio-m2m/requestauthentication.yaml)), via `RequestAuthentication` objects
2. `AuthorizationPolicy` objects of components, for allowing access from Istio IngressGateway, will need to be extended for also requiring a JWT
3. Backends that need to be accessible from other user-namespaces will need to have an `AuthorizationPolicy` that allows any request, only if it has a JWT
4. Backends do not need logic to validate JWTs or check for their presence
6. `RequestAuthentication` objects, per issuer, should expose the corresponding token claims to the `kubeflow-userid` and `kubeflow-groups` headers
7. Backends only need to care about `kubeflow-userid` and `kubeflow-groups` headers
#### Requiring a JWT
For services that expect user identity, the service mesh will need to reject requests without a JWT with HTTP 403.

This can be achieved in multiple ways:
- By using `requestPrincipals`
- By using `request.auth.claims[iss]` in the `when` condition of an `AuthorizationPolicy` rule

The recommended way is to use `requestPrincipals: ["*"]`, as the [Istio documentation suggests](https://istio.io/latest/docs/tasks/security/authorization/authz-jwt/), to accept only requests that have a valid JWT.

An administrator can further limit access to Kubeflow services based on specific issuers by updating the `AuthorizationPolicies`
to use `request.auth.claims[iss]` instead.

With these changes, the `AuthorizationPolicy` for `jupyter-web-app` should look like this:
```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  labels:
    app: jupyter-web-app
    kustomize.component: jupyter-web-app
  name: jupyter-web-app
  namespace: kubeflow
spec:
  action: ALLOW
  rules:
  - from:
    - source:
        principals:
        - cluster.local/ns/istio-system/sa/istio-ingressgateway-service-account
        requestPrincipals: # new! Require JWT
        - '*'
  selector:
    matchLabels:
      app: jupyter-web-app
```

Similarly, KFP API Server `AuthorizationPolicy`, for allowing requests from all namespaces, should be:
```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  labels:
    app.kubernetes.io/component: ml-pipeline
    app.kubernetes.io/name: kubeflow-pipelines
    application-crd-id: kubeflow-pipelines
  name: ml-pipeline
  namespace: kubeflow
spec:
  rules:
  - from:
    - source:
        principals:
        - cluster.local/ns/kubeflow/sa/ml-pipeline
        - cluster.local/ns/kubeflow/sa/ml-pipeline-ui
        - cluster.local/ns/kubeflow/sa/ml-pipeline-persistenceagent
        - cluster.local/ns/kubeflow/sa/ml-pipeline-scheduledworkflow
        - cluster.local/ns/kubeflow/sa/ml-pipeline-viewer-crd-service-account
        - cluster.local/ns/kubeflow/sa/kubeflow-pipelines-cache
  - from:
    - source:
        requestPrincipals: # new! Allow request from any source, as long as it has JWT
        - '*'
  selector:
    matchLabels:
      app: ml-pipeline
```
