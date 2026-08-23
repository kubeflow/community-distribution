#!/usr/bin/env bash

# Common functions for Kubeflow manifest synchronization scripts

setup_error_handling() {
  set -euxo pipefail
  IFS=$'\n\t'
}

# Helm v4 renders template files differently from v3, so a chart must be
# rendered with the major version that the idempotence workflow pins.
require_helm_major_version() {
  local version
  version="$(helm version --template '{{.Version}}')"
  if [[ "$version" != v"$1".* ]]; then
    echo "ERROR: Helm v$1.x required to match the idempotence workflow, found $version." >&2
    exit 1
  fi
}

# Check if the git repository has uncommitted changes
check_uncommitted_changes() {
  if [ -n "$(git status --porcelain)" ]; then
    echo "WARNING: You have uncommitted changes"
  fi
}

# Create a new git branch if it doesn't exist
create_branch() {
  if [[ "${KUBEFLOW_SYNCHRONIZE_NO_COMMIT:-}" == "true" ]]; then
    return
  fi
  local branch="$1"
  check_uncommitted_changes
  if ! git show-ref --verify --quiet refs/heads/$branch; then
    git checkout -b "$branch"
  else
    echo "Branch $branch already exists."
  fi
}

clone_and_checkout() {
  local source_directory="$1"
  local repository_url="$2"
  local repository_directory="$3"
  local commit="$4"
  mkdir -p "$source_directory"
  cd "$source_directory"
  # Clone repository if it doesn't exist
  if [ ! -d "$repository_directory/.git" ]; then
    git clone "$repository_url" "$repository_directory"
  fi
  # Checkout the requested reference.
  cd "$source_directory/$repository_directory"
  # Refresh every reference so that a cached clone never checks out a stale
  # branch and so that freshly cloned branches resolve to their remote head.
  git fetch --force --tags origin
  if git rev-parse --verify --quiet "refs/remotes/origin/${commit}" >/dev/null; then
    # The reference is a remote branch: create or reset a local branch so it
    # always points at the fetched remote head instead of the default branch.
    git checkout -B "$commit" "origin/${commit}"
  else
    # The reference is a tag or a commit identifier: check it out directly.
    git checkout --force "$commit"
  fi
  check_uncommitted_changes
}

# Copy manifests from source to destination
copy_manifests() {
  local source="$1"
  local destination="$2"
  if [ -d "$destination" ]; then
    rm -r "$destination"
  fi
  cp "$source" "$destination" -r
}

# Update README with new commit reference
update_readme() {
  local manifests_directory="$1"
  local source_text="$2"
  local destination_text="$3"
  if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i "" "s|$source_text|$destination_text|g" "${manifests_directory}/README.md" # BSD sed of Mac OSX
  else
    sed -i "s|$source_text|$destination_text|g" "${manifests_directory}/README.md" # GNU sed of Linux
  fi
}

update_helm_chart_application_version() (
  local chart_yaml="$1"
  local application_version="$2"
  local application_version_field_count
  local commit_identifier_pattern='^[0-9a-fA-F]{7,40}$'
  local escaped_application_version
  local semantic_version_pattern='^v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-((0|[1-9][0-9]*)|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)(\.((0|[1-9][0-9]*)|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))*)?(\+[0-9A-Za-z-]+(\.[0-9A-Za-z-]+)*)?$'
  local status
  local temporary_chart=""

  trap 'if [[ -n "$temporary_chart" ]]; then rm -f "$temporary_chart"; fi' EXIT

  if [[ ! "$application_version" =~ $semantic_version_pattern \
    && ! "$application_version" =~ $commit_identifier_pattern ]]; then
    return 1
  fi

  if [[ "$application_version" == *$'\n'* || "$application_version" == *$'\r'* ]]; then
    return 1
  fi

  if application_version_field_count="$(awk '/^appVersion:/{count++} END {print count + 0}' "$chart_yaml")"; then
    if [[ "$application_version_field_count" -ne 1 ]]; then
      return 1
    fi
  else
    return $?
  fi

  if escaped_application_version="$(printf '%s' "$application_version" | sed 's/[\\&|]/\\&/g')"; then
    :
  else
    return $?
  fi

  if temporary_chart="$(mktemp "${chart_yaml}.temporary.XXXXXX")"; then
    :
  else
    return $?
  fi
  if ! cp -p "$chart_yaml" "$temporary_chart"; then
    return 1
  fi

  if ! sed -i "s|^appVersion:.*|appVersion: \"${escaped_application_version}\"|" "$temporary_chart"; then
    return 1
  fi

  if ! grep -Fqx -- "appVersion: \"${application_version}\"" "$temporary_chart"; then
    return 1
  fi

  if mv "$temporary_chart" "$chart_yaml"; then
    temporary_chart=""
    return 0
  else
    status=$?
    return "$status"
  fi
)

write_generated_file_atomically() (
  local destination_file="$1"
  shift
  local destination_directory
  local status
  local temporary_file=""

  trap 'if [[ -n "$temporary_file" ]]; then rm -f "$temporary_file"; fi' EXIT

  if [[ "$#" -eq 0 ]]; then
    return 1
  fi

  if destination_directory="$(dirname "$destination_file")"; then
    :
  else
    return $?
  fi
  if [[ ! -d "$destination_directory" ]]; then
    return 1
  fi

  if temporary_file="$(mktemp "${destination_file}.temporary.XXXXXX")"; then
    :
  else
    return $?
  fi

  if [[ -e "$destination_file" ]]; then
    if ! cp -p "$destination_file" "$temporary_file"; then
      return 1
    fi
  elif ! chmod 0644 "$temporary_file"; then
    return 1
  fi

  if "$@" > "$temporary_file"; then
    :
  else
    status=$?
    return "$status"
  fi

  if mv "$temporary_file" "$destination_file"; then
    temporary_file=""
    return 0
  else
    status=$?
    return "$status"
  fi
)

# Commit changes to git repository
commit_changes() {
  if [[ "${KUBEFLOW_SYNCHRONIZE_NO_COMMIT:-}" == "true" ]]; then
    return
  fi
  local manifests_directory="$1"
  local commit_message="$2"
  local paths_to_add=("${@:3}")
  cd "$manifests_directory"
  for path in "${paths_to_add[@]}"; do
    git add "$path"
  done
  git commit -s -m "$commit_message"
}
