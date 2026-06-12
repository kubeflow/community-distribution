# Standardise JWTs Usage

**Authors**: Kimonas Sotirchos @kimwnasptd

## Requirements
- OIDC logic, via [Istio external authoriser](https://istio.io/latest/docs/tasks/security/authorization/authz-custom/), should be adding `id_token` to http requests in `Authorization: Bearer <token>` headers
## Scope
This proposal aims to standardise how the Kubeflow backends should be handling the user information (name of user, groups they belong to), living in JWTs and http headers.

This proposal takes as a requirement that users should be able to use K8s Tokens as `Authorization: Bearer <token>` headers in their request from inside the cluster. Note that the issuer of the tokens should not be relevant to the Kubeflow applications. It'll be up to the service-mesh to verify them, and be able to work with multiple issuers (i.e. Dex, K8s etc). The applications will only care about the user/groups information from the tokens.
### In
- Which component should be validating JWTs (id-tokens from OIDC or K8s ServiceAccount tokens)
- Define where the backends should expect to find user related information
- Define how different token issuers (i.e. Dex, K8s etc) should be handled
### Out
- Proposing code changes to existing components
## Current State
As of Kubeflow 1.8 the user information has been injected into requests as the `kubeflow-userid` header, from the AuthService (replaced by `oauth2-proxy`). For this approach to be secure there are the following patterns that Kubeflow follows:
1. Backends in the `kubeflow` namespace that need to know the user identity rely on `kubeflow-userid` headers in http requests.
2. The AuthService adds the `kubeflow-userid` header to all authenticated requests.
3. Only requests from the Istio IngressGateway are trusted to have the `kubeflow-userid` header
    1. Backends that are not exposed to user namespaces (i.e. jupyter-web-app) are only reachable via the Istio IngressGateway.
    2. The KFP backend [explicitly drops requests](https://github.com/kubeflow/community-distribution/blob/96ce068e16b2a707464471bddc0d2a58e403d1fc/apps/pipeline/upstream/base/installs/multi-user/istio-authorization-config.yaml#L37) from user namespaces if they have this header
    3. In-cluster Pods that want to talk to `kubeflow` workloads, which understands identity, are [using a K8s ServiceAccount Token](https://www.kubeflow.org/docs/components/pipelines/v1/sdk/connect-api/#full-kubeflow-subfrom-inside-clustersub)
### Limitations
- Not able to express `AuthorizationPolicies` for group header in Istio
- Limited possibility to use custom JWT claims as a source of information about the authenticated user

To accommodate the above limitations and improve the authentication and authorization flow in terms of security, maintenance and flexibility
we propose to add the JWT to the `Authorization` header, so it can be digested by Istio and have the user details securely
injected into the `Authorization` headers. This will also enable us to define policies in the future for better handling of groups.
https://istio.io/latest/docs/tasks/security/authorization/authz-jwt/

But the above creates the following topics that require an agreement on how to handle them:
1. There will be `id_tokens` from different issuers (i.e. from Dex, K8s) that the platform will need to handle
2. Information of user is both in `kubeflow-userid` and in `id_token` of http request, for Kubeflow components to deduce the identity from
3. It's not clear if backends should be validating the JWT (i.e. KFP right now validates ServiceAccount tokens [`1`](https://github.com/kubeflow/pipelines/blob/2.2.0/backend/src/apiserver/auth/authenticator_token_review.go#L47-L58) [`2`](https://github.com/kubeflow/pipelines/blob/2.2.0/backend/src/apiserver/resource/resource_manager.go#L1698-L1699) )

## Specification
The goal of this proposal is to provide a uniform way for all backends to handle identity tokens and to specify
which levels of the stack are responsible for which parts.

This spec proposes to standardise on the following high level agreement, for new backends:
1. Requests hitting `kubeflow` apps, which expect user identity in requests, should have a JWT in `Authorization: Bearer <token>` header
2. The service-mesh is responsible for validating the JWTs
    1. The service-mesh must drop (401) a request if the JWT is invalid (`RequestAuthentication`)
    2. The service-mesh must drop (403) a request if the JWT is not present, and the application expects requests to have a user identity (`AuthorizationPolicy`)
3. The backends are not responsible for validating the JWTs or their existence
4. The service-mesh must expose user and groups to `kubeflow-userid` and `kubeflow-groups` headers, after validating JWTs
    1. if the mesh will not override these headers, then users could forge requests and impersonate other users by setting the header and any valid token
    1. for User to Machine traffic, the `email` claim from `id_token` should be used by default but it should also allow parameterization to allow using different claims. This is doable via `RequestAuthentication` with object per issuer
    2. in case of K8s ServiceAccount tokens the `sub` claim will be used. `sub` claim format is `system:serviceaccount:<sa-namespace>:<sa-name>`
    3. in case of Dex tokens it would be `kimonas@email.com`
5. The backends will use the information from the headers and not deal with JWTs
    1. `SubjectAccessReviews` should be made for the `user` and `groups` that were exposed from the headers, independently of the issuer of the token
    2. [`SubjectAccessReview API`](https://kubernetes.io/docs/reference/kubernetes-api/authorization-resources/subject-access-review-v1/) uses the `user`,
       `groups`, `resource` and `verb` details to verify the access against K8s RBAC, which allows defining authorization to specific actions based on
       K8s standard RBAC implementation

With the above implementation we move all the logic of handling the JWTs to the service-mesh and leave only the business logic to the apps. This also means that the apps don't care about token "types" (i.e. dex, k8s tokens etc) and only have to look at the corresponding headers.

This proposal aims to put more focus on keeping and validating `id_tokens` but also bridging to the existing functionality of the backends, to avoid extensive changes.
### Implementation
The technical details for the above proposal translate to the following
1. Common Kubeflow manifests, for all components, for configuring Istio for supporting multiple issuers ([Dex](https://github.com/kubeflow/community-distribution/blob/v1.9-branch/common/oauth2-proxy/components/istio-external-auth/requestauthentication.dex-jwt.yaml) and [K8s-m2m](https://github.com/kubeflow/community-distribution/blob/v1.9-branch/common/oauth2-proxy/components/istio-m2m/requestauthentication.yaml)), via `RequestAuthentication` objects
2. `AuthorizationPolicy` objects of components, for allowing access from Istio IngressGateway, will need to be extended for also requiring a JWT
3. Backends that need to be accessible from other user-namespaces will need to have an `AuthorizationPolicy` that allows any request, only if it has a JWT
4. Backends don't need any logic for validating the JWTs and their existence
6. `RequestAuthentication` objects, per issuer, should expose the corresponding token claims to the `kubeflow-userid` and `kubeflow-groups` headers
7. Backends only need to care about `kubeflow-userid` and `kubeflow-groups` headers
#### Requiring a JWT
The service-mesh will need to drop requests (403) that don't have any JWT, for services that expect user identity in the requests.

This can be achieved in multiple ways:
- By using `requestPrincipals`
- By using `request.auth.claims[iss]` in the `when` condition of an `AuthorizationPolicy` rule

The recommended way is to use `requestPrincipals: ["*"]`, as the [Istio docs suggest](https://istio.io/latest/docs/tasks/security/authorization/authz-jwt/), to accept only requests that have a valid JWT.

If an admin would like to further limit access to Kubeflow services based on specific issuers, they can do so by updating the `AuthorizationPolicies`
to instead use `request.auth.claims[iss]`.

From the above, the `AuthorizationPolicy` for the jupyter-web-app should look like:
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
