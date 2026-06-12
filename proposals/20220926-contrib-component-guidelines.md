# Guidelines for /contrib Components

**Authors**: Kimonas Sotirchos kimwnasptd@arrikto.com

The motivation behind this proposal is to fully document expectations and
requirements that components under `/contrib` should satisfy. This will make it
more clear how to use a component, how it integrates with Kubeflow, the problems
it tries to solve as well as dependency versions.

## Goals

* Document requirements that components under `/contrib` should satisfy
* Introduce a process for deprecating unmaintained components

## Non-Goals

* Get into the discussion of which components are considered "Kubeflow" components
    * The assumption until now is that components under the Kubeflow GitHub Org live
      under the `/apps` dir, and all others under `/contrib`
* Provide a migration plan for components to move out from `/contrib`
* Modify the [`example/kustomization.yaml`](https://github.com/kubeflow/community-distribution/blob/master/example/kustomization.yaml) with new components

## Proposal

### Component Requirements

Components living under `/contrib` should satisfy some strict requirements to
ensure they are always usable by end-users and contain complementary documentation.

These are the requirements for all components under `/contrib`:
1. There must be a `README.md` file that documents:
    * Instructions on how someone can install the component in a Kubeflow cluster
        * Since Kubeflow manifests have standardized on [Kustomize](https://kustomize.io/)
          we expect all manifests to be a kustomize packages
    * How to use the component as part of Kubeflow (examples)
    * The problems it tries to solve and the value it brings
    * Links to the official documentation of the component
2. There must be an OWNERS file with at least 2 users
3. The component must work with the latest version of Kubeflow, and its
   dependencies
4. There must be an `UPGRADE.md` file that documents any instructions users need
   to follow when applying manifests of a newer version
5. There needs to be sufficient work on testing
    * There must be a script file [python, bash etc] that vefiries the component
      is working as expected. This can be something very simple, like submitting a
      CustomResource and waiting for it to become Ready
    * The maintainers will need to work with the leads of Manifests WG to ensure
      there's some basic automation in place that will be running the above script(s)
6. All pods must run with the [baseline PSS set](https://kubernetes.io/docs/concepts/security/pod-security-standards/#baseline)
7. [stretch goal] All pods must run according to the offical Kubernetes
   [podsecuritystandards restricted set](https://kubernetes.io/docs/concepts/security/pod-security-standards/#restricted).
   This means explicitly no root containers and dropping all capabilities in your pods securitycontexts.
8. [stretch goal] Running with Istio sidecars
9. [stretch goal] Namespace isolation

At this point we don't want to provide too much of a strict structure for the
README. Developers are free to expose any other information in the README that
they find fit, as long as the above info is exposed.


### Deprecation plan

The proposed criteria for deciding that a component should be deprecated are:
1. The component can not be installed in the minimum K8s version supported by Kubeflow
2. The manifests are not working as expected and result in undeployable Pods
3. The documented examples do not work as expected

If a component meets all the above criteria then it will initially be marked as
UNMAINTAINED/OUT-OF-DATE, in the component's README. Then if a whole Kubeflow release
cycle concludes and the component is still in UNMAINTAINED/OUT-OF-DATE phase and
without any feedback from the OWNERS, it will be removed.
