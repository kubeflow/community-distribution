#!/usr/bin/env python3

import argparse
import subprocess
import sys

from pathlib import Path

path_to_synchronization_script = {
    "applications/dashboard/upstream": "scripts/synchronize-dashboard-manifests.sh",
    "applications/hub/upstream": "scripts/synchronize-hub-manifests.sh",
    "applications/katib/upstream": "scripts/synchronize-katib-manifests.sh",
    "applications/kserve/kserve/upstream": "scripts/synchronize-kserve-kserve-manifests.sh",
    "applications/kserve/kserve-ui/upstream": "scripts/synchronize-kserve-ui-manifests.sh",
    "applications/notebooks-v1/upstream": "scripts/synchronize-notebooks-v1-manifests.sh",
    "applications/pipeline/upstream": "scripts/synchronize-pipelines-manifests.sh",
    "applications/spark/spark-operator": "scripts/synchronize-spark-operator-manifests.sh",
    "applications/trainer/upstream": "scripts/synchronize-trainer-manifests.sh",
    "applications/training-operator/upstream": "scripts/synchronize-training-operator-manifests.sh",
    "applications/workspaces/upstream": "scripts/synchronize-kubeflow-workspaces-manifests.sh",
    "common/cert-manager": "scripts/synchronize-cert-manager-manifests.sh",
    "common/dex": "scripts/synchronize-dex-manifests.sh",
    "common/istio": "scripts/synchronize-istio-manifests.sh",
    "common/knative": "scripts/synchronize-knative-manifests.sh",
    "common/oauth2-proxy": "scripts/synchronize-oauth2-proxy-manifests.sh",
}

# convert the strings above into actual path objects for easier handling later
path_to_synchronization_script = {
    Path(k): Path(v) for k, v in path_to_synchronization_script.items()
}


def find_upstream_scripts(changed_files: list[Path]) -> set[Path]:
    upstream_scripts = set()
    for changed in changed_files:
        for upstream_path, script in path_to_synchronization_script.items():
            if upstream_path in changed.parents or changed == upstream_path:
                upstream_scripts.add(script)
    return upstream_scripts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Find synchronization scripts for changed upstream files."
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        metavar="FILE",
        help="Changed file paths to check against tracked upstream directories.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the scripts that would run without executing them.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all synchronization scripts regardless of changed files.",
    )
    args = parser.parse_args()

    if args.all:
        upstream_scripts = set(path_to_synchronization_script.values())
    else:
        upstream_scripts = find_upstream_scripts(args.files)
    failed = False
    for script in sorted(upstream_scripts):
        print(f"Running {script}...")
        if args.dry_run:
            print(f"Skipping {script} due to '--dry-run'")
            continue
        process = subprocess.Popen(
            [script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={"KUBEFLOW_SYNCHRONIZE_NO_COMMIT": "true"},
            text=True,
        )
        output, _ = process.communicate()
        if process.returncode != 0:
            print(output, end="")
            failed = True

    if failed:
        sys.exit(1)
