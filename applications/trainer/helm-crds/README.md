# Trainer API release

Install this parent as `trainer-apis` in `kubeflow-system`; its internal
`trainer-api-payload` dependency is not an independently installed release.
It owns the TrainJob, TrainingRuntime, ClusterTrainingRuntime and JobSet
definitions. Each definition is an ordinary template with
`helm.sh/resource-policy: keep`, allowing explicit updates while retaining
objects on uninstall. A rollback can still downgrade a retained definition.

See [the component installation and lifecycle contract](../helm/README.md)
for prerequisites, exact commands, compatibility, retention and recovery.
