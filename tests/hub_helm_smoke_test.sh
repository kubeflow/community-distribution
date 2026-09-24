#!/usr/bin/env bash
# The upstream demo source contains models; a 404 or an empty list is not success.
set -euo pipefail
temporary_directory=$(mktemp -d)
kubectl port-forward -n kubeflow service/model-catalog 18082:8080 >"$temporary_directory/forward.log" 2>&1 &
forward_pid=$!
# Called indirectly by the EXIT trap.
# shellcheck disable=SC2329
cleanup() {
  kill "$forward_pid" 2>/dev/null || true
  wait "$forward_pid" 2>/dev/null || true
  rm -rf "$temporary_directory"
}
trap cleanup EXIT
for ((attempt=0; attempt<90; attempt++)); do
  if curl --fail --silent --max-time 5 http://localhost:18082/api/model_catalog/v1alpha1/models \
      -o "$temporary_directory/models.json" && \
      python3 - "$temporary_directory/models.json" <<'PYTHON'
import json, sys
with open(sys.argv[1]) as stream:
    result = json.load(stream)
assert isinstance(result, dict) and isinstance(result.get("items"), list)
assert result["items"], "the demo catalog must return at least one model"
assert all(isinstance(item, dict) and item.get("name") for item in result["items"])
PYTHON
  then
    echo 'Catalog returned HTTP 200 and nonempty model contents.'
    exit 0
  fi
  sleep 2
done
echo 'Catalog did not return a nonempty model list before timeout.' >&2
exit 1
