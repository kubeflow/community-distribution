#!/usr/bin/env python3

import argparse
import copy
import shlex
import shutil
import subprocess
import sys
import tempfile

import yaml

from pathlib import Path
from typing import Any

GENERATOR_SCRIPT = "scripts/generate-pipelines-helm-manifests.py"
DEFAULT_OUTPUT_PATH = Path("applications/pipeline/helm/manifests")
DEFAULT_KUSTOMIZE_BINARY = "kustomize"
ROLE_BASED_ACCESS_CONTROL_API_GROUP = "rbac.authorization.k8s.io"
PLATFORM_DATABASE_KUSTOMIZE_PATH = Path("applications/pipeline/overlays")
PLATFORM_KUBERNETES_NATIVE_KUSTOMIZE_PATH = Path(
    "applications/pipeline/upstream/env/cert-manager/"
    "platform-agnostic-multi-user-k8s-native"
)


def resource_identity(resource: dict[str, Any]) -> tuple[str, str, str, str]:
    api_version = resource.get("apiVersion")
    kind = resource.get("kind")
    metadata = resource.get("metadata")

    if not isinstance(api_version, str) or not api_version:
        raise ValueError("Resource must contain apiVersion")
    if not isinstance(kind, str) or not kind:
        raise ValueError("Resource must contain kind")
    if not isinstance(metadata, dict):
        raise ValueError("Resource must contain metadata")

    name = metadata.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("Resource must contain metadata.name")

    namespace = metadata.get("namespace", "")
    if not isinstance(namespace, str):
        raise ValueError("Resource metadata.namespace must be a string")

    return api_version, kind, namespace, name


def index_resources(
    resources: list[dict[str, Any]],
    scenario_name: str,
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    indexed_resources = {}

    for resource in resources:
        identity = resource_identity(resource)
        if identity in indexed_resources:
            raise ValueError(
                f"Duplicate resource identity in {scenario_name}: {identity}"
            )
        indexed_resources[identity] = resource

    return indexed_resources


def partition_scenarios(
    platform_database_resources: list[dict[str, Any]],
    platform_kubernetes_native_resources: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    database_index = index_resources(
        platform_database_resources,
        "platform-database",
    )
    kubernetes_native_index = index_resources(
        platform_kubernetes_native_resources,
        "platform-k8s-native",
    )
    identical_identities = {
        identity
        for identity in database_index.keys() & kubernetes_native_index.keys()
        if database_index[identity] == kubernetes_native_index[identity]
    }

    partitions = {
        "common_crds": [],
        "common_resources": [],
        "platform_database_crds": [],
        "platform_database_resources": [],
        "platform_kubernetes_native_crds": [],
        "platform_kubernetes_native_resources": [],
    }

    for resource in platform_database_resources:
        identity = resource_identity(resource)
        if identity in identical_identities:
            partition_name = (
                "common_crds"
                if resource["kind"] == "CustomResourceDefinition"
                else "common_resources"
            )
        else:
            partition_name = (
                "platform_database_crds"
                if resource["kind"] == "CustomResourceDefinition"
                else "platform_database_resources"
            )
        partitions[partition_name].append(resource)

    for resource in platform_kubernetes_native_resources:
        identity = resource_identity(resource)
        if identity in identical_identities:
            continue
        partition_name = (
            "platform_kubernetes_native_crds"
            if resource["kind"] == "CustomResourceDefinition"
            else "platform_kubernetes_native_resources"
        )
        partitions[partition_name].append(resource)

    return partitions


def add_crd_retention_annotation(
    resource: dict[str, Any],
) -> dict[str, Any]:
    rendered_resource = copy.deepcopy(resource)
    metadata = rendered_resource.setdefault("metadata", {})
    annotations = metadata.setdefault("annotations", {})
    annotations["helm.sh/resource-policy"] = "keep"
    return rendered_resource


def is_aggregated_cluster_role(resource: dict[str, Any]) -> bool:
    """Tell whether the aggregation controller owns the rules of a resource.

    Decided by the API group, the kind and a valid aggregation rule, never by
    a name prefix or a label: a ClusterRole that only contributes to another
    one through its labels owns its rules.
    """
    api_version = resource.get("apiVersion")
    if not isinstance(api_version, str):
        return False
    api_group, separator, _ = api_version.partition("/")
    if not separator or api_group != ROLE_BASED_ACCESS_CONTROL_API_GROUP:
        return False
    if resource.get("kind") != "ClusterRole":
        return False

    aggregation_rule = resource.get("aggregationRule")
    if not isinstance(aggregation_rule, dict):
        return False
    cluster_role_selectors = aggregation_rule.get("clusterRoleSelectors")
    return isinstance(cluster_role_selectors, list) and bool(cluster_role_selectors)


def omit_empty_aggregated_cluster_role_rules(
    resource: dict[str, Any],
) -> dict[str, Any]:
    """Omit the empty rules field of an aggregated ClusterRole.

    The aggregation controller owns the rules of such a ClusterRole. With Helm
    4 server-side apply, a payload that ships even `rules: []` claims the
    field, and every later `helm upgrade` fails with a conflict with
    clusterrole-aggregation-controller. Absent rules stay absent, empty rules
    are removed and never written as `rules: null`, and nonempty rules are an
    error, never discarded. Every other resource is returned unchanged.
    """
    rendered_resource = copy.deepcopy(resource)
    if not is_aggregated_cluster_role(rendered_resource):
        return rendered_resource
    if "rules" not in rendered_resource:
        return rendered_resource

    if rendered_resource["rules"] not in (None, []):
        name = resource_identity(rendered_resource)[3]
        raise ValueError(
            f"Aggregated ClusterRole {name} has nonempty rules; the generator "
            "omits only the empty rules field of an aggregated ClusterRole "
            "and never discards permissions"
        )
    del rendered_resource["rules"]
    return rendered_resource


def render_partition_payload(
    resources: list[dict[str, Any]],
    source_kustomize_path: str,
) -> str:
    """Render a payload file.

    The payload is plain YAML read with .Files.Get, so Helm never evaluates it
    and Go template delimiters inside upstream manifests survive verbatim.
    Which payload applies is decided by the chart, not written in here.

    The resources are those of `kustomize build` with exactly two controlled
    transforms: a CustomResourceDefinition gains the annotation
    `helm.sh/resource-policy: keep`, and an aggregated ClusterRole loses its
    empty rules field. Both are applied here, at serialization, so the
    scenarios are still partitioned by their Kustomize output.
    """
    rendered_resources = [
        (
            add_crd_retention_annotation(resource)
            if resource["kind"] == "CustomResourceDefinition"
            else omit_empty_aggregated_cluster_role_rules(resource)
        )
        for resource in resources
    ]
    manifest_text = yaml.safe_dump_all(
        rendered_resources,
        default_flow_style=False,
        explicit_start=False,
        explicit_end=False,
        sort_keys=False,
        width=100,
    )

    return (
        "# Code generated by scripts/generate-pipelines-helm-manifests.py.\n"
        "# Do not edit. Refresh with scripts/synchronize-pipelines-manifests.sh.\n"
        f"# Source Kustomize path: {source_kustomize_path}\n"
        f"{manifest_text}"
    )


def write_generated_payloads(
    generated_payloads: dict[str, str],
    output_directory: Path,
) -> None:
    for file_name, file_content in generated_payloads.items():
        if Path(file_name).name != file_name:
            raise ValueError(
                f"Generated payload file name must not contain a path: {file_name}"
            )
        if not isinstance(file_content, str):
            raise TypeError(f"Generated payload content must be a string: {file_name}")

    output_directory.parent.mkdir(parents=True, exist_ok=True)
    staging_directory = Path(
        tempfile.mkdtemp(
            prefix=f".{output_directory.name}.new.",
            dir=output_directory.parent,
        )
    )
    backup_directory = output_directory.with_name(f".{output_directory.name}.backup")

    try:
        for file_name, file_content in generated_payloads.items():
            (staging_directory / file_name).write_text(file_content)

        if backup_directory.exists():
            raise FileExistsError(
                f"Generated payload backup directory already exists: {backup_directory}"
            )

        if output_directory.exists():
            output_directory.rename(backup_directory)

        try:
            staging_directory.rename(output_directory)
        except Exception:
            if backup_directory.exists() and not output_directory.exists():
                backup_directory.rename(output_directory)
            raise
        else:
            if backup_directory.exists():
                shutil.rmtree(backup_directory)
    finally:
        if staging_directory.exists():
            shutil.rmtree(staging_directory)


def build_generated_payloads(
    platform_database_resources: list[dict[str, Any]],
    platform_kubernetes_native_resources: list[dict[str, Any]],
) -> dict[str, str]:
    partitions = partition_scenarios(
        platform_database_resources,
        platform_kubernetes_native_resources,
    )
    common_source_description = (
        "applications/pipeline/overlays and "
        "applications/pipeline/upstream/env/cert-manager/"
        "platform-agnostic-multi-user-k8s-native"
    )
    database_source = "applications/pipeline/overlays"
    kubernetes_native_source = (
        "applications/pipeline/upstream/env/cert-manager/"
        "platform-agnostic-multi-user-k8s-native"
    )

    return {
        "common-crds.yaml": render_partition_payload(
            partitions["common_crds"], common_source_description
        ),
        "common-resources.yaml": render_partition_payload(
            partitions["common_resources"], common_source_description
        ),
        "platform-database-crds.yaml": render_partition_payload(
            partitions["platform_database_crds"], database_source
        ),
        "platform-database-resources.yaml": render_partition_payload(
            partitions["platform_database_resources"], database_source
        ),
        "platform-kubernetes-native-crds.yaml": render_partition_payload(
            partitions["platform_kubernetes_native_crds"], kubernetes_native_source
        ),
        "platform-kubernetes-native-resources.yaml": render_partition_payload(
            partitions["platform_kubernetes_native_resources"],
            kubernetes_native_source,
        ),
    }


def load_yaml_resources(rendered_yaml: str, source_name: str) -> list[dict[str, Any]]:
    resources = []
    for document_number, document in enumerate(
        yaml.safe_load_all(rendered_yaml),
        start=1,
    ):
        if document is None:
            continue
        if not isinstance(document, dict):
            raise ValueError(
                f"YAML document {document_number} from {source_name} "
                "must be a mapping"
            )
        resource_identity(document)
        resources.append(document)
    return resources


def render_kustomize_path(
    repository_root: Path,
    kustomize_path: Path,
    kustomize_binary: str,
) -> list[dict[str, Any]]:
    result = subprocess.run(
        [kustomize_binary, "build", str(kustomize_path)],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Kustomize rendering failed for {kustomize_path}:\n{result.stderr}"
        )
    return load_yaml_resources(result.stdout, str(kustomize_path))


def render_generated_payloads(
    repository_root: Path,
    kustomize_binary: str,
) -> dict[str, str]:
    platform_database_resources = render_kustomize_path(
        repository_root,
        PLATFORM_DATABASE_KUSTOMIZE_PATH,
        kustomize_binary,
    )
    platform_kubernetes_native_resources = render_kustomize_path(
        repository_root,
        PLATFORM_KUBERNETES_NATIVE_KUSTOMIZE_PATH,
        kustomize_binary,
    )
    return build_generated_payloads(
        platform_database_resources,
        platform_kubernetes_native_resources,
    )


def check_generated_payloads(
    generated_payloads: dict[str, str],
    output_directory: Path,
) -> list[tuple[str, str]]:
    """Compare what generation would write with what the output directory holds.

    Returns a sorted list of (status, relative path) where status is "stale"
    (bytes differ), "missing" (would be generated, absent on disk) or "extra"
    (present on disk, would not be generated; generation deletes such a file).
    Bytes are compared, not decoded text, so a line-ending change is a
    difference. Nothing is written.
    """
    expected = {
        Path(file_name): file_content.encode("utf-8")
        for file_name, file_content in generated_payloads.items()
    }

    actual = set()
    if output_directory.is_dir():
        actual = {
            path.relative_to(output_directory)
            for path in output_directory.rglob("*")
            if not path.is_dir()
        }

    differences = []
    for relative_path, file_content in expected.items():
        if relative_path not in actual:
            differences.append(("missing", relative_path.as_posix()))
        elif (output_directory / relative_path).read_bytes() != file_content:
            differences.append(("stale", relative_path.as_posix()))
    for relative_path in actual - set(expected):
        differences.append(("extra", relative_path.as_posix()))
    return sorted(differences, key=lambda difference: difference[1])


def repair_command(arguments: argparse.Namespace) -> str:
    """Return the shell command that regenerates exactly the checked tree.

    The command is meant to be run from the repository root, so every path is
    resolved, and it is quoted for a shell because a path can contain spaces.
    Only the options that differ from the defaults are carried.
    """
    command = ["python3", GENERATOR_SCRIPT]
    if arguments.repository_root is not None:
        command += ["--repository-root", str(arguments.repository_root.resolve())]
    if arguments.output_directory is not None:
        command += ["--output-directory", str(arguments.output_directory.resolve())]
    if arguments.kustomize_binary != DEFAULT_KUSTOMIZE_BINARY:
        command += ["--kustomize-binary", arguments.kustomize_binary]
    return shlex.join(command)


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    argument_parser = argparse.ArgumentParser(
        description=(
            "Generate deduplicated Kubeflow Pipelines Helm manifest templates "
            "from the supported Kustomize scenarios."
        )
    )
    argument_parser.add_argument(
        "--repository-root",
        type=Path,
        default=None,
        help="Path to the Kubeflow community distribution repository root.",
    )
    argument_parser.add_argument(
        "--output-directory",
        type=Path,
        help=f"Generated payload directory. Defaults to {DEFAULT_OUTPUT_PATH}.",
    )
    argument_parser.add_argument(
        "--kustomize-binary",
        default=DEFAULT_KUSTOMIZE_BINARY,
        help="Kustomize executable name or path.",
    )
    argument_parser.add_argument(
        "--check",
        action="store_true",
        help="Report payloads that regeneration would change, without writing.",
    )
    return argument_parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    default_repository_root = Path(__file__).resolve().parents[1]
    repository_root = (arguments.repository_root or default_repository_root).resolve()
    output_directory = (
        arguments.output_directory.resolve()
        if arguments.output_directory
        else repository_root / DEFAULT_OUTPUT_PATH
    )
    displayed_output_directory = (
        output_directory.relative_to(repository_root)
        if output_directory.is_relative_to(repository_root)
        else output_directory
    )

    try:
        generated_payloads = render_generated_payloads(
            repository_root,
            arguments.kustomize_binary,
        )
        if arguments.check:
            differences = check_generated_payloads(
                generated_payloads,
                output_directory,
            )
        else:
            write_generated_payloads(generated_payloads, output_directory)
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if not arguments.check:
        print(
            f"Generated {len(generated_payloads)} Kubeflow Pipelines payload files "
            f"in {displayed_output_directory}."
        )
        return 0

    if differences:
        print(
            f"ERROR: Kubeflow Pipelines payloads in {displayed_output_directory} "
            f"are not what {GENERATOR_SCRIPT} generates:",
            file=sys.stderr,
        )
        for status, file_name in differences:
            print(f"  {status:8} {file_name}", file=sys.stderr)
        print(f"Regenerate with: {repair_command(arguments)}", file=sys.stderr)
        return 1

    print(f"Kubeflow Pipelines payloads in {displayed_output_directory} are fresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
