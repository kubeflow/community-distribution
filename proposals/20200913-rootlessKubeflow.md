# Rootless Kubeflow

Authors: Julius von Kohout (@juliusvonkohout)

### Goals

We want to run Kubeflow with as few root privileges as possible, in accordance with CNCF and Kubernetes best practices.
Most enterprise environments will require this as well.

### Implementation details
The main steps are to add a profile for Istio CNI and later the ambient mesh, and to update the documentation and manifest generation process.
Only Istio CNI or the Istio ambient mesh can run without root privileges, as explained at https://istio.io/latest/docs/setup/additional-setup/cni/.
Istio CNI will still need a DaemonSet in `kube-system`, but that is isolated from user workloads.
The ambient mesh should remove this requirement and also remove the Istio initialization containers and sidecars.
The next step is to add the baseline and restricted PSS as a Kustomize component under `/contrib` and extend the Profile controller to annotate user namespaces with configurable PSS labels.

We want to use a staged approach.

#### First Stage:
1. Implement Istio 1.17.5 and use it by default, because 1.17 is the version planned for Kubeflow 1.8.
2. Implement Istio CNI (`--set components.cni.enabled=true --set components.cni.namespace=kube-system`) as a second option.
3. Add simple tests similar to `tests/gh-actions/install_istio.sh` and `tests/gh-actions/install_knative.sh` for Istio CNI. Support both rootful and rootless Istio at the same time and give users one release for testing.

#### Second stage:
4. Add pod security standards (https://kubernetes.io/docs/concepts/security/pod-security-standards/) `base/restricted` to `manifests/contrib`
5. Enforce baseline PSS (advanced users can still build OCI containers with Podman and Buildah, but not Docker-in-Docker). Baseline PSS should work with any Istio configuration. Otherwise, we will move this item to the third stage, after Istio CNI or the ambient mesh becomes the default.
7. Enable warnings for violations of restricted PSS.
8. Add tests to make sure that PSS are used and tested in continuous integration.
9. Optionally enforce restricted PSS, which may affect minor corner cases.

#### Third stage:
9. Upgrade Istio to 1.19 to make the ambient mesh available
10. Add istio-ambient as an option to the next Kubeflow release.

#### Fourth stage:
11. Use the ambient service mesh by default in Kubeflow 1.10.

### Non-Goals
This covers cluster-level security, not application-level CVEs.

### Does this break any existing functionality?
Not so far. Only restricted PSS may block Docker-in-Docker, which poses security risks.
This is a rarely used feature from the KFP SDK.
With baseline PSS, you can still build OCI images with tools such as Podman.
We should replace Docker with Podman, which has a compatible command-line interface, in the KFP SDK: https://kubeflow-pipelines.readthedocs.io/en/1.8.22/source/kfp.containers.html?highlight=kfp.containers.build_image_from_working_dir#kfp.containers.build_image_from_working_dir.


### Does this fix/solve any outstanding issues?
This proposal enables Kubeflow to implement parts of Kubernetes best practices and improve the usage in enterprise and regulated environments.
The progress is tracked in https://github.com/kubeflow/community-distribution/issues/2528
