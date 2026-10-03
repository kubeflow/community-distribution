# Trainer runtime catalog

Install as `trainer-runtimes` in `kubeflow-system` only after the Trainer APIs,
controllers and admission webhooks are ready. This chart owns the eight default
ClusterTrainingRuntime objects as ordinary resources. It has no install/delete
hooks, pruning label or blanket keep annotation.

Uninstall deletes its catalog objects. Before uninstall or removal, inventory
all referencing TrainJobs, including queued and suspended jobs. A runtime
snapshot does not bypass live-runtime admission checks on job updates.
Administrator-created runtimes with other names are not owned by this chart.

See [the component installation and lifecycle contract](../helm/README.md)
for exact commands, runtime update/rollback semantics and removal preflight.
