# Kubernetes M2M Authentication with Istio and RequestAuthentication

## Overview

This kustomize component enables M2M (Machine-to-Machine) authentication in Kubernetes, using
Istio and the `RequestAuthentication` object. It configures Istio to trust JWTs (JSON Web Tokens)
in Authorization Bearer tokens when the JWT issuer matches the one in `RequestAuthentication`. The
default setup uses Kubernetes' self-served OIDC issuer with self-signed certificates.

In Kubernetes clusters managed by platform providers, the OIDC issuer is usually managed by the
provider and served behind publicly trusted certificates. In these cases, it is advisable to use
the platform-managed Kubernetes OIDC issuer in the `RequestAuthentication` for seamless integration
and authentication compliance with the platform's security standards.
