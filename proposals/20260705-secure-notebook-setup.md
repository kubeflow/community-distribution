# Secure Notebook Setup

Authors: Lorin Lehawany (@lorinl), Sven Nobis (@SvenTo)

## Goal/Motivation

These features add support for running notebooks on their own subdomains. This prevents session hijacking through a malicious notebook. It is recommended for production setups.

## Description

The multi-domain setup is recommended for a production Kubeflow deployment because the default setup allows an authenticated attacker to hijack sessions. However, because the setup has prerequisites and is not suitable for local development environments, it cannot be enabled by default.

This setup hosts the Kubeflow dashboard and APIs on a separate domain from the notebooks to prevent session hijacking from malicious notebooks through the user’s agent (browser). If an attacker hosts malicious notebooks and convinces a victim to visit the notebook’s URL, the attacker cannot steal session data or make API requests in the victim’s name.

## Prerequisite

If you want to enable the multi-domain setup, you need to meet the following prerequisites:

- A wildcard domain for Kubeflow or some kind of automated external domain management for the notebook domains (e.g., [ExternalDNS](https://github.com/kubernetes-sigs/external-dns)).
- A wildcard TLS certificate for Kubeflow or some kind of automated certificate management for the notebook domains (e.g., [cert manager](https://cert-manager.io/docs/)).

This includes that Kubeflow is exposed externally (which is most likely given in a production environment):

- Istio ingress is exposed externally (required for subdomain routing).
- OAuth2 Proxy and Dex are exposed externally.

For instance, a minimal configuration to expose Kubeflow on an external domain requires the following settings:

**OAuth2/Dex**

The internal cluster Dex URLs should be replaced with the external Kubeflow ingress URL for OIDC issuer, token redemption, and JWKS endpoints in [``common/oauth2-proxy/base/oauth2_proxy.cfg``](../common/oauth2-proxy/base/oauth2_proxy.cfg). This example uses ``kubeflow.example.org`` as the external domain:

```sh
oidc_issuer_url = "https://kubeflow.example.org/dex"
redeem_url = "http://kubeflow.example.org/dex/token"
oidc_jwks_url = "http://kubeflow.example.org/dex/keys"
```

As well as the JWT issuer in the file [``common/oauth2-proxy/components/istio-external-auth/requestauthentication.dex-jwt.yaml``](../common/oauth2-proxy/components/istio-external-auth/requestauthentication.dex-jwt.yaml):

```sh
  jwtRules:
  - issuer: https://kubeflow.example.org/dex
```

As well as the JWT issuer in the dex configuration file [``common/dex/overlays/oauth2-proxy/config-map.yaml``](../common/dex/overlays/oauth2-proxy/config-map.yaml):

```sh
data:
  config.yaml: |
    issuer: https://kubeflow.example.org/dex
```

Secondly, the Kubeflow Ingress Gateway needs to be exposed via HTTPS:

**Istio Service**

The Istio service needs to be exposed to the outside. Change the service type to ``LoadBalancer`` in the file [`common/istio/istio-install/base/patches/service.yaml`](../common/istio/istio-install/base/patches/service.yaml):

```yaml
apiVersion: v1
kind: Service
metadata:
  name: istio-ingressgateway
  namespace: istio-system
spec:
  type: LoadBalancer
```

**Kubeflow Gateway**

The Kubeflow gateway should enable HTTPS, and a TLS certificate needs to be referenced in the file [`common/istio/kubeflow-istio-resources/base/kf-istio-resources.yaml`](../common/istio/kubeflow-istio-resources/base/kf-istio-resources.yaml):

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: Gateway
metadata:
  name: kubeflow-gateway
spec:
  selector:
    istio: ingressgateway
  servers:
  - port:
      number: 80
      name: http
      protocol: HTTP
    hosts:
    - "*"
  - port:
      number: 443
      name: https
      protocol: HTTPS
    hosts:
    - "*"
    tls:
      mode: SIMPLE
      credentialName: https-credential # set this to the secret with the wildcard TLS certificate and key
```

This will make the setup work. Please ensure that you follow the recommendations in the [_Security Considerations_ section](code/kubeflow-manifests/README.md) section for guidance on a secure setup.

## Implementation details to enable multi-domain setup

The list below shows all steps required to enable the multi-domain setup and shows how to configure them.

The notebooks subdomains must be a part of the Kubeflow authentication authority. In a default setup, this means that the notebooks domain is a subdomain of the Kubeflow dashboard. Otherwise, the setup will not work. For instance, if the dashboard is hosted on ``kubeflow.example.org``, the profile's `example` notebook will be hosted on `example-notebook.kubeflow.example.org` by setting the `ISTIO_HOST_NOTEBOOK` parameter to `${NAMESPACE}-notebook.kubeflow.example.org`.

**Environment parameters**

The following parameters need to be defined in the configuration file [`applications/notebooks-v1/upstream/notebook-controller/manager/params.env`](../applications/notebooks-v1/upstream/notebook-controller/manager/params.env):

| Parameter                       | Description                                                                                                                                                          |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ISTIO_USE_NOTEBOOK_SUBDOMAINS` | Set this value to ``true``.                                                                                                                                          |
| `ISTIO_HOST_NOTEBOOK`           | Domain template used by Istio to host notebooks (e.g., `${NAMESPACE}-notebook.kubeflow.example.org`). `${NAMESPACE}` will be replaced with the Notebook's namespace (Kubeflow profile). |
| `ISTIO_HOST_AUTH`               | Host used by Istio for handling authentication callbacks or login flows (e.g., `kubeflow.example.org`).                                                              |
| `ISTIO_AUTH_PATH`               | Optional, defaults to `/oauth2/`; Can be used to change the base URL path used by Istio for authentication callbacks or login flows (e.g. `/oauth2/`).                                        |
|                                 | This path must match the routing configured in the authentication provider (e.g., OAuth2 Proxy) so that login and callback requests are correctly handled.           |

**Cookie domains**

Enable this setting for multi-domain notebook support in the configuration file [`common/oauth2-proxy/base/oauth2_proxy.cfg`](../common/oauth2-proxy/base/oauth2_proxy.cfg):

```sh
cookie_domains = [ "kubeflow.example.org" ]
```

## Does this break any existing functionality?

The multi-domain setup is not enabled by default and thus this change will not change any default behavior. It should not break any existing functionality if enabled, too.

## Does this solve any outstanding security issues?

Yes. This implementation addresses a security issue that could allow session hijacking via a malicious notebook; see [the GitHub security advisory](https://github.com/kubeflow/notebooks/security/advisories/GHSA-qjw6-hpc7-w36h) for details.