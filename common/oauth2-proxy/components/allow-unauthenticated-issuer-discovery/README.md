# Unauthenticated Issuer Discovery

If you are using Kubernetes with tools like kind, vCluster, minikube, or similar solutions for local
development, it is highly likely that the Kubernetes OIDC issuer operates within the cluster and is
secured with self-signed certificates.

To facilitate the use of machine-to-machine tokens with `oauth2-proxy` and Istio, both tools must perform OIDC
discovery for the token issuer. Kubernetes offers OIDC discovery functionality at a specific
URI:
```
https://kubernetes.default.svc.cluster.local/.well-known/openid-configuration
```

Access to this endpoint is blocked by default due to RBAC policies, but it can be enabled by
creating a `ClusterRoleBinding`. This binding associates the predefined `ClusterRole`
`system:service-account-issuer-discovery` with the `system:unauthenticated` group. The
configuration for this is detailed in the resource file `clusterrolebinding.unauthenticated-oidc-viewer.yaml`.

Once this step is completed, the endpoint can be accessed to reveal the Issuer URL:
```bash
$ curl -k https://kubernetes.default.svc.cluster.local/.well-known/openid-configuration

# Example output in kind:
{"issuer":"https://kubernetes.default.svc.cluster.local","jwks_uri":"https://172.18.0.5:6443/openid/v1/jwks","response_types_supported":["id_token"],"subject_types_supported":["public"],"id_token_signing_alg_values_supported":["RS256"]}

# Example output in vCluster:
{"issuer":"https://kubernetes.default.svc.cluster.local","jwks_uri":"https://1.2.3.4:6443/openid/v1/jwks","response_types_supported":["id_token"],"subject_types_supported":["public"],"id_token_signing_alg_values_supported":["RS256"]}

# Example output in AWS EKS:
{"issuer":"https://oidc.eks.region.amazonaws.com/id/123abc","jwks_uri":"https://ip-1-2-3-4.eu-central-1.compute.internal:443/openid/v1/jwks","response_types_supported":["id_token"],"subject_types_supported":["public"],"id_token_signing_alg_values_supported":["RS256"]}
```

If you are operating in a `vCluster`, access to the endpoint specified under `jwks_uri` (for example,
`https://1.2.3.4:6443/openid/v1/jwks`) is managed separately, and merely creating the previously
mentioned `ClusterRoleBinding` is insufficient. To circumvent this limitation, you can configure the
`kube-apiserver` to allow anonymous authentication by setting `--anonymous-auth=true`. This is
achieved by appending `--kube-apiserver-arg=anonymous-auth=true` to the list of arguments in the
Helm Chart Values file:
```yaml
vcluster:
    extraArgs:
    - --kube-apiserver-arg=anonymous-auth=true
```
