### Clean Coding standards

- The first reference documentation is the root level readme.md.
- We do test-driven development (GitHub actions and scripts in /tests)
- Deleting code and adding tests is often more important than adding code.
- Code, documentation and feedback shall be in line with principal level scientific elegance, minimalism, conciseness and precision.
- Use explicitly long, expressive, pronounceable well chosen names instead of short abbreviating names. Complain about misnaming explicitly. Here is a list of mandatory rules unless there is hard technical evidence that it would break code when refactoring: app -> Application, admin -> administrator / administrate, dep -> dependencies / department, repo -> repository, sync -> synchronization / synchronize, dev -> development / developer, prod -> production / produce, temp / tmp -> temporary, auth -> authentication/ authorization, deploy -> deployment / deploy, cred -> credentials, tmp/temp -> temporary, prep -> prepare, regex -> regular expression, diff -> difference, infra -> infrastructure. This mandatory rule applies to all AI model internal thinking stages, reasoning steps, code comments, planned tasks, todo items, tool invocation parameters, tool descriptions, and user-facing communications. Trying to "save" letters is unprofessional and decreases readability. Code, documentation, internal thoughts, action descriptions, reviews, and suggestions must be completely free of these blacklisted abbreviations unless technically necessary, and must be fully readable as proper, formal technical English text. English contractions (such as "I'm", "I'll", "don't", "can't") are strictly forbidden in all communications, documentation, comments, and thoughts; use full spelling instead (such as "I am", "I will", "do not", "cannot", "must not"), especially elaborated, well-readable, and precise English.
- Language should aim to be less context-dependent. Authentication is something entirely different than authorization, auto could mean automobile or automation, deps could be departments or dependencies. Blacklist such typical incorrect abbreviations, but whitelist very popular context-free acronyms such as OIDC, API, CPU, GPU. Make sure to use correct grammar. They is plural, not singular and must only be used in plural. A company or team or contributor for example is a single abstract entity, so it is definitely not a plural they.
The expectation for the contributor is that he must understand all changes he is proposing as if he had written the changes himself.
- Code is more often read than written and most of the costs come from maintenance.
- What is not tested is not supported. Automation is the best documentation.
- We do trunk-based development in the master branch.
- When referring to Kubernetes fields in prose, spell them out (say "the specification" not "the spec") except where a literal YAML key must stay verbatim.
- We support only Linux.
- And as a reminder to never output incorrect English in any PR creations or reviews, the AI model must not output any English text that is grammatically incorrect, unprofessional, or contains any of the blacklisted abbreviations. The AI model must always output fully readable, formal, and precise English text in all communications, documentation, comments, and internal thoughts.
- It is illegal to change any file / path containing "/upstream" without using the synchronization scripts in /scripts. Block such violating PRs.

## Repository structure

- `applications` holds the official Kubeflow components, each synchronized from its upstream repository into an `upstream` subtree.
- `common` holds the shared services (Istio, Knative, Cert Manager, Dex, OAuth2-Proxy, namespaces and roles) maintained by the Manifests Working Group.
- `experimental` holds third-party integrations and platform experiments, including the Helm charts under `experimental/helm`.
- `scripts` holds the synchronization scripts that regenerate every `upstream` subtree; these are the only sanctioned way to change such paths.
- `tests` holds the installation and verification scripts, `releases` the release handbooks, and `proposals` the design documents.

## Architecture

- Every external request enters through the Istio ingress gateway, is authenticated by Dex and OAuth2-Proxy, and is then routed by the Istio service mesh, which also enforces authentication between the components.
- The Central Dashboard aggregates the per-component user interfaces (Pipelines, Katib, Notebooks, Volumes, KServe UI, Model Registry, Trainer) behind that single authenticated entry point.
- The control plane is a set of controllers that reconcile custom resources: the Argo-based `ml-pipeline` stack, Katib, the Notebook controller, KServe (backed by Knative), Trainer, the Hub (which bundles Model Registry and Model Catalog) and the Spark operator, supported by shared storage (SeaweedFS S3, per-component MySQL databases and the Hub PostgreSQL catalog).
- The Profile controller projects every user or team into an isolated namespace that carries its own service accounts, role bindings, secrets, Istio authorization policies and persistent volume claims; all workloads (workbenches, pipeline runs, experiments, model serving, distributed training and Spark applications) run inside these namespaces.
- Cert Manager issues the certificates for the admission webhooks that the controllers rely on.

```text
                     +-------------------------------+
                     |  External request (browser)   |
                     +---------------+---------------+
                                     |
                                     v
                     +-------------------------------+
                     |  Istio ingress gateway (TLS)  |
                     +---------------+---------------+
                                     |
                                     v
                     +-------------------------------+
                     |      Authentication edge      |
                     |  Dex (OIDC) <-> OAuth2-Proxy  |
                     +---------------+---------------+
                                     |
                                     v
                     +-------------------------------+
                     |      Istio service mesh       |
                     | (authenticates traffic among  |
                     |         the components)       |
                     +---------------+---------------+
                                     |
                                     v
      +------------------------------------------------------------+
      |  Central Dashboard  (aggregates the component UIs)         |
      |  Pipelines | Katib | Notebooks | Volumes | KServe UI |     |
      |  Model Registry | Trainer                                  |
      +------------------------------+-----------------------------+
                                     |
                                     v
      +------------------------------------------------------------+
      |  Control plane: controllers reconcile custom resources     |
      |  ml-pipeline (Argo) | Katib | Notebook controller |        |
      |  KServe (Knative) | Trainer | Spark operator |             |
      |  Hub = Model Registry + Model Catalog | Profile controller |
      +---------------+--------------------------+-----------------+
                      |                          |
                      v                          v
   +----------------------------+   +--------------------------------+
   |  Shared storage            |   |  Per-user / per-team namespace |
   |  SeaweedFS S3              |   |  (projected by the Profile     |
   |  per-component MySQL       |   |   controller)                  |
   |  Hub PostgreSQL (catalog)  |   |  service accounts, role        |
   +----------------------------+   |  bindings, secrets, Istio      |
                                    |  authorization policies, PVCs, |
                                    |  and all workloads:            |
                                    |  workbenches, pipeline runs,   |
                                    |  experiments, model serving,   |
                                    |  distributed training, Spark   |
                                    +--------------------------------+

   Cert Manager issues the certificates for the controllers' admission webhooks.
```

## Testing and continuous integration

- Every component ships an installation script and, where applicable, a verification test under `tests`, written in Bash or Python.
- The GitHub Actions workflows in `.github/workflows` provision an ephemeral KinD cluster, install the components and run these tests on every pull request and on every push to `master`.
- The full end-to-end installation is validated by `full_kubeflow_integration_test.yaml`; individual components are validated by their dedicated workflow.
- The Helm charts are checked for parity against the Kustomize manifests through `tests/helm_kustomize_compare.sh` and its `helm-kustomize-comparison.yml` workflow.

## Tooling

- Kustomize is the primary rendering tool; the experimental Helm charts are an additional, optional deployment path.
- Pre-commit hooks enforce the formatting and linting standards: yamllint, shellcheck and black, alongside the basic hygiene hooks configured in `.pre-commit-config.yaml`.
- All linters and hooks exclude the `upstream` subtrees, which are owned by their source repositories and regenerated through the synchronization scripts in `scripts`.

## Key documentation

- [README.md](README.md) is the primary reference: installation, the component version matrix, upgrading and extending, and the frequently asked questions.
- [common/oauth2-proxy/README.md](common/oauth2-proxy/README.md) explains the Istio external authorization edge, the Kubeflow Pipelines TokenReview and SubjectAccessReview flow, and how to bypass Dex and connect OAuth2-Proxy directly to an external identity provider.
- [common/dex/README.md](common/dex/README.md) documents the Dex and Keycloak (OpenID Connect) integration.
- [common/istio/README.md](common/istio/README.md) covers the Istio CNI default, the Google Kubernetes Engine and ambient-mode overlays, sidecar egress pruning and the KServe virtual-service routing conflicts.
- [common/kubeflow-roles/README.md](common/kubeflow-roles/README.md) describes the aggregated ClusterRole pattern that projects roles into user Profiles.
- [experimental/README.md](experimental/README.md) states the component requirements from [proposals/20220926-contrib-component-guidelines.md](proposals/20220926-contrib-component-guidelines.md); the KEP-style proposals live under [proposals](proposals) and the release handbooks under [releases](releases).