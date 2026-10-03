# Kubeflow Trainer

The Kustomize installation is `overlays/`.

The [Helm installation](helm/README.md) separates API definitions, the control
plane and the default runtime catalog into three releases. The charts preserve
the distribution overlay and are generated together by the Trainer synchronization
script. They do not manage user TrainJobs or the shared platform namespace.
