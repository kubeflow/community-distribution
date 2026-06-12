# Rootless Kubeflow

Authors: Julius von Kohout (@juliusvonkohout)

### Goals

We want to run Kubeflow as rootless as possible according to CNCF/Kubernetes best practices.
Most enterprise environments will require this as well.

### Implementation details
The main steps are adding an additional profile for istio-cni and later ambient mesh, updating the documentation and manifest generation process.
Only istio-cni or istio ambient mesh can run rootless as explained here https://istio.io/latest/docs/setup/additional-setup/cni/.
Istio-cni will still need a deamonset in kube-system, but that is completly isolated from user workloads.
The ambient mesh should get rid of this as well and also has the benefit of removing the istio initcontainers and sidecars altogether.
Then adding the baseline and restricted PSS as kustomize component to `/contrib` and extending the profile controller to annotate user namespaces with configurable PSS labels.

We want to use a staged approach.

#### First Stage:
1. Implement Istio 1.17.5 and use it by default, because 1.17. is what we have planned to use for Kubeflow 1.8.
2. Implement istio-cni (`--set components.cni.enabled=true --set components.cni.namespace=kube-system`) as second option.
3. Add simple tests similar to `tests/gh-actions/install_istio.sh` and `tests/gh-actions/install_knative.sh` for istio-cni and support both rootfull and rootless istio at the same time and give users one release to test

#### Second stage:
4. Add pod security standards (https://kubernetes.io/docs/concepts/security/pod-security-standards/) `base/restricted` to `manifests/contrib`
5. Enforce PSS baseline (Adavanced users can still build OCI containers via Podman and buildah, but not Docker in Docker). The baseline PSS should works with any istio. If not we will move this item to the third stage after istio-cni or the ambient mesh is the default.
7. Enable Warnings for violations of restricted PSS
8. Add tests to make sure that the PSS are used and tested in the CICD
9. Optionally Enforce PSS restricted (this is where minor corner cases are affected)

#### Third stage:
9. Upgrade Istio to 1.19 to make the ambient mesh available
10. Add istio-ambient as an option to the next Kubeflow release.

#### Fourth stage:
11. Use the ambient service mesh by default in Kubeflow 1.10.

### Non-Goals
This does not cover Application level CVEs, only cluster level security.

### Does this break any existing functionality?
So far not. Only PSS restricted may block the security-wise dangerous Docker in Docker.
This is a rarely used feature from the KFP SDK.
With PSS baseline you can still build OCI images with Podman for example.
We should replace Docker with the cli compatible podman in the KFP SDK https://kubeflow-pipelines.readthedocs.io/en/1.8.22/source/kfp.containers.html?highlight=kfp.containers.build_image_from_working_dir#kfp.containers.build_image_from_working_dir.


### Does this fix/solve any outstanding issues?
This proposal enables Kubeflow to implement parts of Kubernetes best practices and improve the usage in enterprise and regulated environments.
The progress is tracked in https://github.com/kubeflow/community-distribution/issues/2528
