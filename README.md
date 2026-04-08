# Kubeflow AI reference platform deployment manifests

![build checks status](https://github.com/kubeflow/manifests/actions/workflows/full_kubeflow_integration_test.yaml/badge.svg?branch=master)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/9940/badge)](https://www.bestpractices.dev/projects/9940)

This repository helps you to install Kubeflow Platform in popular Kubernetes clusters such as Kind, Minikube, Rancher, EKS, AKS, and GKE. The manifests include all Kubeflow components (Pipelines, KServe, etc.), the **Kubeflow Central Dashboard**, and other applications that comprise the **Kubeflow Platform**. It is used and adapted around the world by small and large enterprises alike that have strict legal, security and multi-tenancy requirements for their machine learning platforms. Nevertheless it is also beneficial for academic users wanting to explore the end-to-end capabilities of the Kubeflow Platform and contribute to it.

For a stable and conservative experience, we recommend using the [latest stable release](https://github.com/kubeflow/manifests/releases). However, please consult the more up-to-date documentation in the master branch.
You can also install the master branch of [`kubeflow/manifests`](https://github.com/kubeflow/manifests) by following the instructions [here](https://github.com/kubeflow/manifests?tab=readme-ov-file#installation) and providing us with feedback. Our continuous integration workflow runs end-to-end installation and tests on pull requests and pushes to the `master` branch in the upstream `kubeflow/manifests` repository; see the [full Kubeflow integration test workflow](https://github.com/kubeflow/manifests/actions/workflows/full_kubeflow_integration_test.yaml) for details.

We are planning to cut 2 releases per year, for example 26.03 and 26.10 before each KubeCon EU and NA.
We ask each working group/component to provide non-breaking patch releases for 6 months based on the version in each date release.
We try to BEST-EFFORT support each release for 6 months as community. There is [commercial support](https://www.kubeflow.org/docs/started/support/#support-from-commercial-providers-in-the-kubeflow-ecosystem) available if needed.
The working groups (KFP, Katib, Trainer, ...) are allowed to release new component versions with breaking changes, but they will only be included in the master branch or the next date release.
This should only apply to “stable” components, as “alpha/beta” components might release breaking changes in patch releases.

## Table of Contents

<!-- toc -->

- [Overview of the Kubeflow Platform](#overview-of-the-kubeflow-platform)
- [Kubeflow Components Versions](#kubeflow-components-versions)
- [Installation](#installation)
  - [Prerequisites](#prerequisites)
  - [Install with a Single Command](#install-with-a-single-command)
  - [Install Individual Components](#install-individual-components)
  - [Connect to Your Kubeflow Cluster](#connect-to-your-kubeflow-cluster)
  - [Change Default User Name](#change-default-user-name)
  - [Change Default User Password](#change-default-user-password)
- [Upgrading and Extending](#upgrading-and-extending)
- [Release Process](#release-process)
- [Security](#security)
- [Pre-commit Hooks](#pre-commit-hooks)
- [Architecture](#architecture)
- [Frequently Asked Questions](#frequently-asked-questions)

<!-- tocstop -->

## Overview of the Kubeflow Platform

- This repository is owned by the [Platform/Manifests/security Working Group](https://github.com/kubeflow/community/blob/master/wg-manifests/charter.md).
- You can join the CNCF Slack and access our meetings at the [Kubeflow Community](https://www.kubeflow.org/docs/about/community/) website.
- Our channel on the CNCF Slack is [**#kubeflow-platform**](https://app.slack.com/client/T08PSQ7BQ/C073W572LA2).
- You can also find our [biweekly meetings](https://bit.ly/kf-wg-manifests-meet), including the commentable [Agenda](https://bit.ly/kf-wg-manifests-notes).
- If you want to contribute, please take a look at the [CONTRIBUTING.md](CONTRIBUTING.md).

The Kubeflow Platform/Manifests repository is organized under three main directories, which include manifests for installing:

| Directory | Purpose |
| - | - |
| `applications` | Kubeflow's official components, maintained by the respective Kubeflow WGs |
| `common` | Common services, maintained by the Manifests WG |
| `experimental` | Third-party integrations and platform experiments (e.g., Ray or security improvements) |

All components are deployable with `kustomize`. In addition, experimental Helm charts for selected components are available under [`experimental/helm/`](experimental/helm/). You can choose to deploy the entire Kubeflow platform or individual components.

## Kubeflow Components Versions

### Kubeflow Version: Master

This repository periodically synchronizes all official Kubeflow components from the respective upstream repositories. The following matrix shows the git version included for each component along with the rough resource requirements for each Kubeflow component, calculated as the maximum of actual usage and configured requests for CPU/memory as well as storage requirements from PVCs:

| Component | Local Manifests Path | Upstream Revision | CPU (millicores) | Memory (Mi) |  PVC Storage (GB) |
| - | - | - | - | - | - |
| Training Operator | applications/training-operator/upstream | [v1.9.2](https://github.com/kubeflow/training-operator/tree/v1.9.2/manifests) | 3m | 25Mi | 0GB |
| Trainer | applications/trainer/upstream | [v2.2.0](https://github.com/kubeflow/trainer/tree/v2.2.0/manifests) | 8m | 143Mi | 0GB |
| Notebook Controller | applications/jupyter/notebook-controller/upstream | [v1.10.0](https://github.com/kubeflow/kubeflow/tree/v1.10.0/components/notebook-controller/config) | 5m | 93Mi | 0GB |
| PVC Viewer Controller | applications/pvcviewer-controller/upstream | [v1.10.0](https://github.com/kubeflow/kubeflow/tree/v1.10.0/components/pvcviewer-controller/config) | 15m | 128Mi | 0GB |
| Tensorboard Controller | applications/tensorboard/tensorboard-controller/upstream | [v1.10.0](https://github.com/kubeflow/kubeflow/tree/v1.10.0/components/tensorboard-controller/config) | 15m | 128Mi | 0GB |
| Central Dashboard | applications/dashboard/upstream/centraldashboard | [v2.0.0-rc.1](https://github.com/kubeflow/dashboard/tree/v2.0.0-rc.1/components/centraldashboard/manifests/kustomize) | 2m | 159Mi | 0GB |
| Profiles + KFAM | applications/dashboard/upstream/profile-controller | [v2.0.0-rc.1](https://github.com/kubeflow/dashboard/tree/v2.0.0-rc.1/components/profile-controller/manifests/kustomize) | 7m | 129Mi | 0GB |
| PodDefaults Webhook | applications/dashboard/upstream/poddefaults-webhooks | [v2.0.0-rc.1](https://github.com/kubeflow/dashboard/tree/v2.0.0-rc.1/components/poddefaults-webhooks/manifests/kustomize) | 1m | 14Mi | 0GB |
| Jupyter Web Application | applications/jupyter/jupyter-web-app/upstream | [v1.10.0](https://github.com/kubeflow/kubeflow/tree/v1.10.0/components/crud-web-apps/jupyter/manifests) | 4m | 231Mi | 0GB |
| Tensorboards Web Application | applications/tensorboard/tensorboards-web-app/upstream | [v1.10.0](https://github.com/kubeflow/kubeflow/tree/v1.10.0/components/crud-web-apps/tensorboards/manifests) |  |  |  |
| Volumes Web Application | applications/volumes-web-app/upstream | [v1.10.0](https://github.com/kubeflow/kubeflow/tree/v1.10.0/components/crud-web-apps/volumes/manifests) | 4m | 226Mi | 0GB |
| Katib | applications/katib/upstream | [v0.19.0](https://github.com/kubeflow/katib/tree/v0.19.0/manifests/v1beta1) | 13m | 476Mi | 10GB |
| KServe | applications/kserve/kserve | [v0.16.0](https://github.com/kserve/kserve/releases/tag/v0.16.0/install/v0.16.0) | 600m | 1200Mi | 0GB |
| KServe Models Web Application | applications/kserve/models-web-app | [c71ee4309f0335159d9fdfd4559a538b5c782c92](https://github.com/kserve/models-web-app/tree/c71ee4309f0335159d9fdfd4559a538b5c782c92/manifests/kustomize) | 6m | 259Mi  | 0GB |
| Kubeflow Pipelines | applications/pipeline/upstream | [2.16.0](https://github.com/kubeflow/pipelines/tree/2.16.0/manifests/kustomize) | 970m | 3552Mi | 35GB |
| Kubeflow Model Registry | applications/model-registry/upstream | [v0.3.8](https://github.com/kubeflow/model-registry/tree/v0.3.8/manifests/kustomize) | 510m | 2112Mi | 20GB |
| Spark Operator	|	applications/spark/spark-operator	|	[2.5.0](https://github.com/kubeflow/spark-operator/tree/v2.5.0) | 9m | 41Mi | 0GB |
| Istio | common/istio | [1.29.1](https://github.com/istio/istio/releases/tag/1.29.1) | 750m | 2364Mi | 0GB |
| Knative | common/knative/knative-serving <br /> common/knative/knative-eventing | [v1.21.1](https://github.com/knative/serving/releases/tag/knative-v1.21.1) <br /> [v1.21.0](https://github.com/knative/eventing/releases/tag/knative-v1.21.0) | 1450m | 1038Mi | 0GB |
| Cert Manager | common/cert-manager | [1.19.4](https://github.com/cert-manager/cert-manager/releases/tag/v1.19.4) | 3m | 128Mi | 0GB |
| Dex | common/dex | [2.45.0](https://github.com/dexidp/dex/releases/tag/v2.45.0) | 3m | 27Mi | 0GB |
| OAuth2-Proxy | common/oauth2-proxy | [7.14.3](https://github.com/oauth2-proxy/oauth2-proxy/releases/tag/v7.14.3) | 3m | 27Mi | 0GB |
| **Total** | | | **4380m** | **12341Mi** | **65GB** |



## Installation

This section covers the installation from scratch. For the in-place upgrade guide, please jump to the [Upgrading and Extending](#upgrading-and-extending) section.

Although our master branch has extended automated tests and is very stable with trunk-based development, please consider using a stable [release tag/branch](https://github.com/kubeflow/manifests/releases) for a more conservative experience.

We provide two options for installing the official Kubeflow components and common services with Kustomize. The aim is to help users install easily and building distributions of Kubeflow by deriving / deviating from the Kubeflow manifests:

1. Single-command installation of all components under `applications` and `common`
2. Multi-command, individual component installation for `applications` and `common`

The `example` directory contains an example kustomization for the single command to be able to run.

:warning: In both options, we use a default email (`user@example.com`) and password (`12341234`). For any production Kubeflow deployment, you should change the default password by following [the relevant section](#change-default-user-password).

### Prerequisites
- For the specific Kubernetes version per release, consult the [release notes](https://github.com/kubeflow/manifests/releases).
- Our Kind script below will take care of installing continuously tested Kubernetes, Kustomize and Kubectl versions for you.
- We use Kind as default but also support Minikube, Rancher, EKS, AKS, and GKE. GKE might need tiny adjustments documented here in this file and OpenShift is also possible.

### ARM64 / aarch64 note

Kubeflow on ARM64/aarch64 may not be fully supported yet because some OCI images might not be available for `linux/arm64`.
If you hit image pull errors such as “no matching manifest for linux/arm64”, please track/report details in kubeflow/manifests#2745 and take a look at the [Google Summer of Code project for Kubeflow on ARM64](https://www.kubeflow.org/events/upcoming-events/gsoc-2026/#project--end-to-end-arm64-support--validation-on-kubeflow).

---
**NOTE**

`kubectl apply` commands may fail on the first try. This is inherent in how Kubernetes and `kubectl` work (e.g., CR must be created after CRD becomes ready). The solution is to simply re-run the command until it succeeds. For the single-line command, we have included a bash one-liner to retry the command.

---

### Install with a Single Command

#### Prerequisites
- 16+ GB of RAM recommended.
- 8 CPU cores recommended.
- You can exclude components from the `example/kustomization.yaml` to fit Kubeflow into 4-8 GB of memory and 2-4 CPU cores.
- `kind`, `kubectl` and `kustomize` from `./tests/install_KinD_create_KinD_cluster_install_kustomize.sh`
- `podman` (better) or `docker` to run the OCI images for the Kind cluster.
- Linux kernel subsystem changes to support many pods:
    - `sudo sysctl fs.inotify.max_user_instances=2280`
    - `sudo sysctl fs.inotify.max_user_watches=1255360`

#### Create Kind Cluster
```sh
./tests/install_KinD_create_KinD_cluster_install_kustomize.sh
```

#### Save Kubeconfig
```sh
kind get kubeconfig --name kubeflow > /tmp/kubeflow-config
export KUBECONFIG=/tmp/kubeflow-config
```

#### Optionally create a Secret based on existing credentials if you run into Docker Hub pull limits
```sh
docker login
kubectl create secret generic regcred \
    --from-file=.dockerconfigjson=$HOME/.docker/config.json \
    --type=kubernetes.io/dockerconfigjson
```

You can install all Kubeflow official components (residing under `applications`) and all common services (residing under `common`) using the following command:

```sh
while ! kustomize build example | kubectl apply --server-side --force-conflicts -f -; do echo "Retrying to apply resources"; sleep 20; done
```

Once everything is installed successfully, you can access the Kubeflow Central Dashboard [by logging in to your cluster](#connect-to-your-kubeflow-cluster).

Congratulations! You can now start experimenting and running your end-to-end ML workflows with Kubeflow.

### Install Individual Components

In this section, we will install each Kubeflow official component (under `applications`) and each common service (under `common`) separately, using just `kubectl` and `kustomize`. This can help you a lot when debugging your installation or if you are encountering installation problems.

If all the following commands are executed, the result is the same as in the above section of the single command installation. The purpose of this section is to:

- Provide a description of each component and insight on how it gets installed.
- Enable the user or distribution owner to pick and choose only the components he needs.

> **Note:** Many component installation steps below reference scripts from the [`tests/`](tests/) directory. These scripts are the same ones used by our [CI/CD integration test workflow](https://github.com/kubeflow/manifests/blob/master/.github/workflows/full_kubeflow_integration_test.yaml), which ensures the documentation is continuously verified. The scripts also provide better error messages and include sanity checks.

#### Kubeflow Namespace

Create the namespaces where the Kubeflow components will reside. We are in the transition from `kubeflow` to `kubeflow-system`.

Install the Kubeflow namespace:

```sh
kustomize build common/kubeflow-namespace/base | kubectl apply -f -
```

#### Cert-manager

Cert-manager is used by many Kubeflow components to provide certificates for admission webhooks.

```sh
./tests/cert_manager_install.sh
```

#### Istio

Istio is used by most Kubeflow components to secure their traffic, enforce network authorization, and implement routing policies. This installation uses Istio CNI, which eliminates the need for privileged init containers and improves compatibility with Pod Security Standards. If you use Cilium CNI on your cluster, you must configure it properly for Istio as shown [here](https://docs.cilium.io/en/latest/network/servicemesh/istio/); otherwise, you will encounter RBAC access denied on the central dashboard.

Install Istio:

```sh
./tests/istio-cni_install.sh
```

For Google Kubernetes Engine (GKE), use the GKE-specific overlay instead:
```sh
kustomize build common/istio/istio-install/overlays/gke | kubectl apply -f -
```

#### Oauth2-proxy

The oauth2-proxy extends your Istio Ingress-Gateway capabilities to function as an OIDC client. It supports user sessions as well as proper token-based machine-to-machine authentication. Authorization which is completely different from authentication is handled via Kubernetes RBAC and Istio authorizationpolicies.

```sh
echo "Installing oauth2-proxy..."

# Only uncomment ONE of the following overlays, as they are mutually exclusive.
# See `common/oauth2-proxy/overlays/` for more options.

# OPTION 1: works on most clusters, does NOT allow K8s service account
#           tokens to be used from outside the cluster via the Istio ingress-gateway.
#
kustomize build common/oauth2-proxy/overlays/m2m-dex-only/ | kubectl apply -f -
kubectl wait --for=condition=Ready pod -l 'app.kubernetes.io/name=oauth2-proxy' --timeout=180s -n oauth2-proxy

# Option 2: works on Kind, K3D, Rancher, GKE, and many other clusters with the proper configuration, and allows K8s service account tokens to be used
#           from outside the cluster via the Istio ingress-gateway. For example, for automation with GitHub Actions.
#           In the end, you need to patch the issuer and jwksUri fields in the request authentication resource in the istio-system namespace
#           as done in /common/oauth2-proxy/overlays/m2m-dex-and-kind/kustomization.yaml.
#           Please follow the guidelines in the section Upgrading and Extending below for patching.
#           curl --insecure -H "Authorization: Bearer `cat /var/run/secrets/kubernetes.io/serviceaccount/token`"  https://kubernetes.default/.well-known/openid-configuration
#           from a pod in the cluster should provide you with the issuer of your cluster.
#
#kustomize build common/oauth2-proxy/overlays/m2m-dex-and-kind/ | kubectl apply -f -
#kubectl wait --for=condition=Ready pod -l 'app.kubernetes.io/name=oauth2-proxy' --timeout=180s -n oauth2-proxy
#kubectl wait --for=condition=Ready pod -l 'app.kubernetes.io/name=cluster-jwks-proxy' --timeout=180s -n istio-system

# OPTION 3: works on most EKS clusters with K8s service account
#           tokens to be used from outside the cluster via the Istio ingress-gateway.
#           You have to adjust AWS_REGION and CLUSTER_ID in common/oauth2-proxy/overlays/m2m-dex-and-eks/ first.
#
#kustomize build common/oauth2-proxy/overlays/m2m-dex-and-eks/ | kubectl apply -f -
#kubectl wait --for=condition=Ready pod -l 'app.kubernetes.io/name=oauth2-proxy' --timeout=180s -n oauth2-proxy
```

If and after you finish the installation with Kubernetes service account token support, you should be able to create and use the tokens:
```sh
kubectl port-forward svc/istio-ingressgateway -n istio-system 8080:80
TOKEN="$(kubectl -n $KF_PROFILE_NAMESPACE create token default-editor)"
client = kfp.Client(host="http://localhost:8080/pipeline", existing_token=token)
curl -v "localhost:8080/jupyter/api/namespaces/${$KF_PROFILE_NAMESPACE}/notebooks" -H "Authorization: Bearer ${TOKEN}"
```

If you want to use OAuth2 Proxy without Dex and connect it directly to your own IDP, you can refer to this [document](common/oauth2-proxy/README.md#change-default-authentication-from-dex--oauth2-proxy-to-oauth2-proxy-only). However, you can also keep Dex and extend it with connectors to your own IDP as explained in the Dex section below.

#### Kubeflow Istio Resources

Create the Kubeflow Gateway `kubeflow-gateway` and ClusterRole `kubeflow-istio-admin`.

Install Kubeflow Istio resources:

```sh
kustomize build common/istio/kubeflow-istio-resources/base | kubectl apply -f -
```

#### Multi-tenancy components (Profiles + KFAM)

```sh
./tests/multi_tenancy_install.sh
```

#### Dex

Dex is an OpenID Connect (OIDC) identity provider with multiple authentication backends. In this default installation, it includes a static user with the email `user@example.com`. By default, the user's password is `12341234`. For any production Kubeflow deployment, you should change the default password by following [the relevant section](#change-default-user-password).

Install Dex:

```sh
./tests/dex_install.sh
```

To connect to your desired identity providers (LDAP, GitHub, Google, Microsoft, OIDC, SAML, GitLab), please take a look at <https://dexidp.io/docs/connectors/oidc/>. We recommend using OIDC in general since it is compatible with most providers. For example, Azure in the following example. You need to modify <https://github.com/kubeflow/manifests/blob/master/common/dex/overlays/oauth2-proxy/config-map.yaml> and add some environment variables in <https://github.com/kubeflow/manifests/blob/master/common/dex/base/deployment.yaml> by adding a patch section in your main Kustomization file. For guidance, please check out [Upgrading and Extending](#upgrading-and-extending).

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: dex
data:
  config.yaml: |
    issuer: https://$KUBEFLOW_INGRESS_URL/dex
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
    enablePasswordDB: true
    #### WARNING: YOU SHOULD NOT USE THE DEFAULT STATIC PASSWORDS
    #### and patch /common/dex/base/dex-passwords.yaml in a Kustomize overlay or remove it
    staticPasswords:
    - email: user@example.com
      hashFromEnv: DEX_USER_PASSWORD
      username: user
      userID: "15841185641784"
    staticClients:
    # https://github.com/dexidp/dex/pull/1664
    - idEnv: OIDC_CLIENT_ID
      redirectURIs: ["/oauth2/callback"]
      name: 'Dex Login Application'
      secretEnv: OIDC_CLIENT_SECRET
    #### Here come the connectors to OIDC providers such as Azure, GCP, GitHub, GitLab, etc.
    #### Connector config values starting with a "$" will read from the environment.
    connectors:
    - type: oidc
      id: azure
      name: azure
      config:
        issuer: https://login.microsoftonline.com/$TENANT_ID/v2.0
        redirectURI: https://$KUBEFLOW_INGRESS_URL/dex/callback
        clientID: $AZURE_CLIENT_ID
        clientSecret: $AZURE_CLIENT_SECRET
        insecureSkipEmailVerified: true
        scopes:
        - openid
        - profile
        - email
        #- groups # groups might be used in the future
```

For Keycloak, we have rough guidelines in <https://github.com/kubeflow/manifests/blob/master/common/dex/README.md>.


#### Central Dashboard

```sh
./tests/central_dashboard_install.sh
```

#### Admission Webhook

Install the Admission Webhook for PodDefaults:

```sh
kustomize build applications/dashboard/upstream/poddefaults-webhooks/overlays/cert-manager | kubectl apply -f -
```

#### Knative (used by KServe)

```sh
./tests/knative_install.sh
```

Optionally, you can install Knative Eventing, which can be used for inference request logging:

```sh
kustomize build common/knative/knative-eventing/base | kubectl apply -f -
```

#### KServe model serving and KServe models web application

```sh
./tests/kserve_install.sh
```

#### Kubeflow Pipelines

Kubeflow Pipelines offers two deployment options to choose from, each designed for different use cases and operational preferences. The traditional database-based approach stores pipeline definitions in an external database, while the Kubernetes native API mode leverages Kubernetes custom resources for pipeline definition storage and management.

> The default artifact store is now seaweedfs as explained [here](https://medium.com/@hpotpose26/kubeflow-pipelines-embraces-seaweedfs-9a7e022d5571). All the overlays now sets SeaweedFS as the default S3-compatible artifact store for Pipelines. It replaces `minio-service` to route S3 traffic to SeaweedFS and patches the Argo Workflow controller to use it.

##### Pipeline Definitions Stored in the Database

Install the [Multi-User Kubeflow Pipelines](https://www.kubeflow.org/docs/components/pipelines/multi-user/) official Kubeflow component:

```sh
./tests/pipelines_install.sh
```

This installs Argo with the runasnonroot emissary executor. Please note that you are still responsible for analyzing the security issues that arise when containers are run with root access and for deciding if the Kubeflow pipeline main containers are run as runasnonroot. It is generally strongly recommended that all user-accessible OCI containers run with Pod Security Standards [restricted](https://kubernetes.io/docs/concepts/security/pod-security-standards/#restricted) and KFP 2.16.0+ has the capability to set runAsNonRoot, runAsUser and runAsGroup via the SDK and the KFP api server configuration.

##### Pipeline Definitions Stored as Kubernetes Resources

Kubeflow Pipelines can be deployed in Kubernetes native API mode, which stores pipeline definitions as Kubernetes custom resources (`Pipeline` and `PipelineVersion` kinds) instead of using external storage. This mode provides better integration with Kubernetes native tooling and GitOps workflows.

```sh
kustomize build applications/pipeline/upstream/env/cert-manager/platform-agnostic-multi-user-k8s-native | kubectl apply -f -
```

**Using the KFP SDK with Kubernetes Native API Mode:**

For detailed pipeline compilation instructions, please refer to the [Kubeflow Pipelines compilation guide](https://www.kubeflow.org/docs/components/pipelines/user-guides/core-functions/compile-a-pipeline/#compiling-for-kubernetes-native-api-mode).

**Differences in Kubernetes Native API Mode:**

- Pipeline definitions are stored as `Pipeline` and `PipelineVersion` custom resources in Kubernetes.
- Pipeline validation is handled through Kubernetes admission webhooks.
- The REST API transparently handles the translation to Kubernetes API calls.

**Benefits of Kubernetes Native Mode**: This approach is ideal for organizations that prefer Kubernetes-native workflows and want to manage pipelines using standard Kubernetes tools and practices. Pipeline definitions can be managed through multiple interfaces: direct kubectl commands, the Kubeflow Pipelines REST API, and the KFP UI for user-friendly pipeline management.

#### Katib

```sh
./tests/katib_install.sh
```

#### Notebooks 1.0

```sh
kustomize build applications/jupyter/notebook-controller/upstream/overlays/kubeflow | kubectl apply -f -
kustomize build applications/jupyter/jupyter-web-app/upstream/overlays/istio | kubectl apply -f -
```

#### Workspaces (Notebooks 2.0)

This feature is still in development.

#### PVC Viewer Controller

```sh
kustomize build applications/pvcviewer-controller/upstream/base | kubectl apply -f -
```

#### Volumes Web Application

```sh
./tests/volumes_web_application_install.sh
```

#### Tensorboard web application and controller

```sh
kustomize build applications/tensorboard/tensorboards-web-app/upstream/overlays/istio | kubectl apply -f -
kustomize build applications/tensorboard/tensorboard-controller/upstream/overlays/kubeflow | kubectl apply -f -
```

#### Trainer (training operator v2)

```sh
./tests/trainer_install.sh
```

#### Spark Operator

```sh
./tests/spark_install.sh
```

#### User Namespaces

Finally, create a new namespace for the default user (named `kubeflow-user-example-com`).

```sh
export KF_PROFILE=kubeflow-user-example-com
./tests/kubeflow_profile_install.sh
```

### Connect to Your Kubeflow Cluster

After installation, it will take some time for all Pods to become ready. Ensure all Pods are ready before trying to connect; otherwise, you might encounter unexpected errors. To check that all Kubeflow-related Pods are ready, use the following commands:

```sh
kubectl get pods -n cert-manager
kubectl get pods -n istio-system
kubectl get pods -n auth
kubectl get pods -n oauth2-proxy
kubectl get pods -n knative-serving
kubectl get pods -n kubeflow
kubectl get pods -n kubeflow-user-example-com
```

#### Port-Forward

The default way of accessing Kubeflow is via port-forwarding. This enables you to get started quickly without imposing any requirements on your environment. Run the following to port-forward Istio's Ingress-Gateway to local port `8080`:

```sh
kubectl port-forward svc/istio-ingressgateway -n istio-system 8080:80
```

After running the command, you can access the Kubeflow Central Dashboard by doing the following:

1. Open your browser and visit `http://localhost:8080`. You should see the Dex login screen.
2. Log in with the default user's credentials. The default email address is `user@example.com`, and the default password is `12341234`.

#### NodePort / LoadBalancer / Ingress

To connect to Kubeflow using NodePort / LoadBalancer / Ingress, you need to set up HTTPS. The reason is that many of our web applications (e.g., Tensorboard Web Application, Jupyter Web Application, Katib UI) use [Secure Cookies](https://developer.mozilla.org/en-US/docs/Web/HTTP/Cookies#restrict_access_to_cookies), so accessing Kubeflow with HTTP over a non-localhost domain does not work.

Exposing your Kubeflow cluster with proper HTTPS is a straightforward process but depends on your environment. You can expose the `istio-ingressgateway` service in the `istio-system` namespace via nginx-ingress or any other ingress provider. For security reasons, only use `ClusterIP` on the service, not NodePort or something similarly dangerous. There is third-party [commercial support](https://www.kubeflow.org/docs/started/support/) available.

---
**NOTE**

If you absolutely need to expose Kubeflow over HTTP, you can disable the `Secure Cookies` feature by setting the `APP_SECURE_COOKIES` environment variable to `false` in every relevant web app. This is not recommended, as it poses security risks.

---

### Change Default User Name

For security reasons, we don't want to use the default username and email for the default Kubeflow user when installing in security-sensitive environments. Instead, you should define your own username and email before deploying. To define it for the default user:

1. Edit `common/dex/overlays/oauth2-proxy/config-map.yaml` and fill the relevant field with your email and preferred username:

    ```yaml
    ...
      staticPasswords:
      - email: <REPLACE_WITH_YOUR_EMAIL>
        username: <REPLACE_WITH_PREFERRED_USERNAME>
    ```

### Change Default User Password

If you have an identity provider (LDAP, GitHub, Google, Microsoft, OIDC, SAML, GitLab) available, you should use that instead of static passwords and connect it to oauth2-proxy or Dex as explained in the sections above. This is best practice instead of using static passwords.

For security reasons, we do not want to use the default static password for the default Kubeflow user when installing in security-sensitive environments. Instead, you should define your own password and apply it either **before creating the cluster** or **after creating the cluster**.

Pick a password for the default user, with email `user@example.com`, and hash it using `bcrypt`:

    ```sh
    python3 -c 'from passlib.hash import bcrypt; import getpass; print(bcrypt.using(rounds=12, ident="2y").hash(getpass.getpass()))'
    ```

For example, running the above command locally with required packages like _passlib_ would look as follows:
  ```sh
  python3 -c 'from passlib.hash import bcrypt; import getpass; print(bcrypt.using(rounds=12, ident="2y").hash(getpass.getpass()))'
  Password:       <--- Enter the password here
  $2y$12$vIm8CANhuWui0J1p3jYeGeuM28Qcn76IFMaFWvZCG5ZkKZ4MjTF4u <--- GENERATED_HASH_FOR_ENTERED_PASSWORD
  ```

#### Before Creating the Cluster:

1. Edit `common/dex/base/dex-passwords.yaml` and fill the relevant field with the hash of the password you chose:

    ```yaml
    ...
      stringData:
        DEX_USER_PASSWORD: <REPLACE_WITH_HASH>
    ```

#### After Creating the Cluster:

1. Delete the existing secret _dex-passwords_ in the auth namespace using the following command:

    ```sh
    kubectl delete secret dex-passwords -n auth
    ```

2. Create the secret dex-passwords with the new hash using the following command:

    ```sh
    kubectl create secret generic dex-passwords --from-literal=DEX_USER_PASSWORD='REPLACE_WITH_HASH' -n auth
    ```

3. Recreate the _dex_ pod in the auth namespace using the following command:

    ```sh
    kubectl delete pods --all -n auth
    ```

4. Try to log in using the new Dex password.

## Upgrading and Extending

For modifications and in-place upgrades of the Kubeflow platform, we provide a rough description for advanced users:

- Never edit the manifests directly; use Kustomize overlays and [components](https://github.com/kubernetes-sigs/kustomize/blob/master/examples/components.md) on top of the [example.yaml](https://github.com/kubeflow/manifests/blob/master/example/kustomization.yaml).
- This allows you to upgrade by just referencing the new manifests, building with Kustomize, and running `kubectl apply` again.
- You might have to adjust your overlays and components if needed.
- You might need to prune old resources. For that, you would add [labels](https://kubectl.docs.kubernetes.io/references/kustomize/kustomization/labels/) to all your resources from the start.
- With labels, you can use `kubectl apply` with `--prune` and `--dry-run` to list prunable resources.
- Sometimes there are major changes; for example, in the 1.9 release, we switched to oauth2-proxy, which needs additional attention (cleanup istio-system once); or 1.9.1 -> 1.10 `kubectl delete clusterrolebinding meta-controller-cluster-role-binding`
- Nevertheless, with a bit of Kubernetes knowledge, one should be able to upgrade.
- 1.10.2 -> 1.11.0 migrates from minio to seaweedfs, so you should delete minio and maybe migrate your data via S3 commands to seaweedfs.

## Release Process

[Kubeflow release handbook](https://github.com/kubeflow/manifests/blob/master/releases/kubeflow-ai-reference-platform-release-handbook.md).

### Security

To view all past security scans, head to the [Image Extracting and Security Scanning GitHub Action workflow](https://github.com/kubeflow/manifests/actions/workflows/trivy.yaml). In the logs of the workflow, you can expand the `Run image extracting and security scanning script` step to view the CVE logs. You will find a per-image CVE scan and a JSON dump of per-WorkingGroup aggregated metrics. You can run the Python script from the workflow file locally on your machine to obtain the detailed JSON files for any git commit.

For more information please consult the [SECURITY.md](./SECURITY.md).

## Pre-commit Hooks

This repository uses pre-commit hooks to ensure code quality and consistency. The following hooks are configured:

1. **Black** - Python code formatter.
2. **Yamllint** - YAML file linter.
3. **Shellcheck** - Shell script static analysis.

To use these hooks:

1. Install pre-commit:

   ```bash
   pip install pre-commit
   ```

2. Install the git hooks:

   ```bash
   pre-commit install
   ```

The hooks will run automatically on `git commit`. You can also run them manually:

```bash
pre-commit run
```

## Architecture

![Kubeflow Architecture](architecture.svg)


## Frequently Asked Questions

- **Q:** What versions of Istio, Knative, Cert-Manager, Argo, ... are compatible with Kubeflow?
  **A:** Please refer to each individual component's documentation for a dependency compatibility range. For Istio, Knative, Dex, Cert-Manager, and OAuth2 Proxy, the versions in `common` are the ones we have validated.
- **Q:** Can I use Kubeflow in an air-gapped environment?
  **A:** Yes you can. You just need to get the list of images from our [trivy CVE scanning script](https://github.com/kubeflow/manifests/blob/master/tests/trivy_scan.py), mirror them and replace the references in the manifests with kustomize components and overlays, see [Upgrading and Extending](#upgrading-and-extending). You could also use a simple kyverno policy to replace the images at runtime, which could be easier to maintain.
- **Q:** Why does Kubeflow use Istio CNI instead of standard Istio?
  **A:** Istio CNI provides better security by eliminating the need for privileged init containers, making it more compatible with Pod Security Standards (PSS). It also enables native sidecars support introduced in Kubernetes 1.28, which helps address issues with init containers and application lifecycle management.
- **Q:** Why does Istio CNI fail on Google Kubernetes Engine (GKE) with "read-only file system" errors?
  **A:** GKE mounts `/opt/cni/bin` as read-only for security reasons. Use the GKE-specific overlay: `kubectl apply -k common/istio/istio-install/overlays/gke` (or `overlays/ambient-gke` for ambient mode). These overlays use GKE's writable CNI directory at `/home/kubernetes/bin`. For details, see [Istio CNI Prerequisites](https://istio.io/latest/docs/setup/additional-setup/cni/#prerequisites).

