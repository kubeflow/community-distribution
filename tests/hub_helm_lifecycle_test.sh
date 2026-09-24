#!/usr/bin/env bash
# Destructive: run only in a disposable integration environment with both releases.
set -euo pipefail
registry_values=${1:?Supply the registry private values file}
catalog_values=${2:?Supply the catalog private values file}
chart_directory=$(mktemp -d)
trap 'rm -rf "$chart_directory"' EXIT

registry_sql() {
  # Variables expand inside the database container, not on this host.
  # shellcheck disable=SC2016
  kubectl exec -n kubeflow-user-example-com deployment/model-registry-db -c db-container -- \
    sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"' sh "$1"
}
catalog_sql() {
  # Variables expand inside the database container, not on this host.
  # shellcheck disable=SC2016
  kubectl exec -n kubeflow statefulset/model-catalog-postgres -c postgres -- \
    sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -Atc "$1"' sh "$1"
}
secret_digest() {
  kubectl get secret "$2" -n "$1" -o json | python3 -c \
    'import hashlib,json,sys; print(hashlib.sha256(json.dumps(json.load(sys.stdin)["data"],sort_keys=True).encode()).hexdigest())'
}
registry_sql "CREATE TABLE IF NOT EXISTS helm_lifecycle_probe (value text PRIMARY KEY); INSERT INTO helm_lifecycle_probe VALUES ('survives') ON CONFLICT DO NOTHING;"
catalog_sql "CREATE TABLE IF NOT EXISTS helm_lifecycle_probe (value text PRIMARY KEY); INSERT INTO helm_lifecycle_probe VALUES ('survives') ON CONFLICT DO NOTHING;"
registry_secret=$(secret_digest kubeflow-user-example-com model-registry-db-secrets)
catalog_secret=$(secret_digest kubeflow model-catalog-postgres)
registry_claim=$(kubectl get pvc metadata-postgres -n kubeflow-user-example-com -o jsonpath='{.metadata.uid}')

for component in registry catalog; do
  if [[ "$component" == registry ]]; then
    chart=applications/hub/helm; namespace=kubeflow-user-example-com; values_file=$registry_values
    deployment=model-registry-ui
  else
    chart=applications/hub/helm-catalog; namespace=kubeflow; values_file=$catalog_values
    deployment=model-catalog-server
  fi
  release="hub-model-${component}"
  ./tests/hub_helm_install.sh "$component" "$values_file"
  revision=$(helm history "$release" -n "$namespace" -o json | python3 -c 'import json,sys; print(json.load(sys.stdin)[-1]["revision"])')
  cp -a "$chart" "$chart_directory/$component"
  # Exercise a changed workload without introducing an unsupported values dial
  # or restarting catalog's ephemeral database.
  python3 - "$chart_directory/$component/manifests/platform-resources.yaml" "$deployment" <<'PYTHON'
import sys, yaml
from pathlib import Path
path = Path(sys.argv[1])
documents = list(yaml.safe_load_all(path.read_text()))
resource = next(item for item in documents if item and item['kind'] == 'Deployment' and item['metadata']['name'] == sys.argv[2])
resource['spec']['replicas'] = 2
path.write_text(yaml.safe_dump_all(documents))
PYTHON
  helm upgrade "$release" "$chart_directory/$component" -n "$namespace" -f "$values_file" --wait --timeout 5m
  [[ $(kubectl get deployment "$deployment" -n "$namespace" -o jsonpath='{.spec.replicas}') == 2 ]]
  helm rollback "$release" "$revision" -n "$namespace" --wait --timeout 5m
  [[ $(kubectl get deployment "$deployment" -n "$namespace" -o jsonpath='{.spec.replicas}') == 1 ]]
done
[[ $(registry_sql "SELECT value FROM helm_lifecycle_probe") == survives ]]
[[ $(catalog_sql "SELECT value FROM helm_lifecycle_probe") == survives ]]
[[ $(secret_digest kubeflow-user-example-com model-registry-db-secrets) == "$registry_secret" ]]
[[ $(secret_digest kubeflow model-catalog-postgres) == "$catalog_secret" ]]
[[ $(kubectl get pvc metadata-postgres -n kubeflow-user-example-com -o jsonpath='{.metadata.uid}') == "$registry_claim" ]]

# Each uninstall must leave the other service and both namespaces intact.
catalog_uid=$(kubectl get deployment model-catalog-server -n kubeflow -o jsonpath='{.metadata.uid}')
helm uninstall hub-model-registry -n kubeflow-user-example-com --wait --timeout 5m
[[ -z $(kubectl get pvc metadata-postgres -n kubeflow-user-example-com --ignore-not-found -o name) ]]
[[ $(kubectl get deployment model-catalog-server -n kubeflow -o jsonpath='{.metadata.uid}') == "$catalog_uid" ]]
[[ $(catalog_sql "SELECT value FROM helm_lifecycle_probe") == survives ]]
kubectl get namespace kubeflow kubeflow-user-example-com >/dev/null
./tests/hub_helm_install.sh registry "$registry_values"
registry_sql "CREATE TABLE helm_lifecycle_probe (value text PRIMARY KEY); INSERT INTO helm_lifecycle_probe VALUES ('other-release-survives');"
registry_claim=$(kubectl get pvc metadata-postgres -n kubeflow-user-example-com -o jsonpath='{.metadata.uid}')
registry_uid=$(kubectl get deployment model-registry-deployment -n kubeflow-user-example-com -o jsonpath='{.metadata.uid}')
helm uninstall hub-model-catalog -n kubeflow --wait --timeout 5m
[[ $(kubectl get deployment model-registry-deployment -n kubeflow-user-example-com -o jsonpath='{.metadata.uid}') == "$registry_uid" ]]
[[ $(registry_sql "SELECT value FROM helm_lifecycle_probe") == other-release-survives ]]
[[ $(kubectl get pvc metadata-postgres -n kubeflow-user-example-com -o jsonpath='{.metadata.uid}') == "$registry_claim" ]]
kubectl get namespace kubeflow kubeflow-user-example-com >/dev/null
./tests/hub_helm_install.sh catalog "$catalog_values"
echo 'Hub same-version upgrade, rollback, credentials, data and uninstall isolation checks passed.'
