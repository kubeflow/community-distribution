#!/bin/bash
set -euxo pipefail

KF_PROFILE=${1:-kubeflow-user-example-com}

TOKEN="$(kubectl -n ${KF_PROFILE} create token default-editor)"
UNAUTHORIZED_TOKEN="$(kubectl -n default create token default)"

STATUS_CODE=$(curl -v \
  --silent --output /dev/stderr --write-out "%{http_code}" \
  "localhost:8080/workspaces/api/v1/workspaces/${KF_PROFILE}" \
  -H "Authorization: Bearer ${TOKEN}")

if test "${STATUS_CODE}" -ne 200; then
  echo "Error, this call should be authorized to list workspaces in namespace ${KF_PROFILE}."
  exit 1
fi

STATUS_CODE=$(curl -v \
  --silent --output /dev/stderr --write-out "%{http_code}" \
  "localhost:8080/workspaces/api/v1/workspaces/${KF_PROFILE}" \
  -H "Authorization: Bearer ${UNAUTHORIZED_TOKEN}")

if test "${STATUS_CODE}" -ne 403; then
  echo "Error, this call should fail to list workspaces in namespace ${KF_PROFILE}."
  exit 1
fi
