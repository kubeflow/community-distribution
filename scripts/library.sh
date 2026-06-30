#!/usr/bin/env bash

# Common functions for Kubeflow manifest synchronization scripts

setup_error_handling() {
  set -euxo pipefail
  IFS=$'\n\t'
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
  # Checkout to specific commit
  cd "$source_directory/$repository_directory"
  if ! git rev-parse --verify --quiet "$commit"; then
    git checkout -b "$commit"
  else
    git checkout "$commit"
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
