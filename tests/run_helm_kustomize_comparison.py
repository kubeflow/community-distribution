#!/usr/bin/env python3
"""Compare a chart's rendered output against its Kustomize baseline.

Components are discovered, not registered. Every chart declares how it is
compared in its own `ci/comparison.yaml`, so adding a component touches only
that component's directory and never a shared list.
"""

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
COMPARATOR_PATH = Path(__file__).with_name("helm_kustomize_compare.py")
_COMPARATOR_SPEC = importlib.util.spec_from_file_location(
    "helm_kustomize_compare", COMPARATOR_PATH
)
comparator = importlib.util.module_from_spec(_COMPARATOR_SPEC)
_COMPARATOR_SPEC.loader.exec_module(comparator)
# A component may ship sibling charts named helm-<purpose> when its resources
# form more than one release; a chart's own charts/ directory is never a
# component chart of its own.
CHART_GLOBS = (
    "common/*/helm*",
    "common/*/*/helm*",
    "applications/*/helm*",
    "applications/*/*/helm*",
    "experimental/helm/charts/*",
    "experimental/ray/*/helm*",
)
DOCUMENT_SEPARATOR = "\n---\n"
HOOK_ANNOTATION = "helm.sh/hook"
PARTITION_GROUP_NAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?")


class _StrictLoader(yaml.SafeLoader):
    """Reject duplicate keys, which PyYAML otherwise resolves to the last one.

    A repeated scenario name would silently discard every earlier definition and
    quietly reduce parity coverage. scripts/helm_manifest_generator.py refuses
    them for the same reason.
    """


def _no_duplicate_keys(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)


KNOWN_DIFFERENCE_ACTIONS = frozenset(
    ("ignorePodTemplateAnnotations", "compareDataAsYaml", "controllerOwnedWebhookRules")
)
WEBHOOK_CONFIGURATION_KINDS = {
    "MutatingWebhookConfiguration",
    "ValidatingWebhookConfiguration",
}
EXACT_RESOURCE_NAME = re.compile(
    r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*"
)


def _validate_reason(path, family, entry):
    if not isinstance(entry, dict) or not str(entry.get("reason") or "").strip():
        raise ValueError(f"{path}: every {family} entry needs a non-empty 'reason'")


def _validate_pattern(path, family, pattern):
    if (
        not isinstance(pattern, str)
        or len(pattern.split("/")) not in (2, 3)
        or not all(pattern.split("/"))
    ):
        raise ValueError(
            f"{path}: {family} must be 'Kind/name' or 'Kind/namespace/name', "
            f"got {pattern!r}"
        )


def _reject_unknown_fields(path, context, mapping, allowed):
    unknown = set(mapping) - allowed
    if unknown:
        raise ValueError(
            f"{path}: unknown {context} fields: {', '.join(sorted(unknown))}"
        )


def _validate_allowances(path, descriptor):
    """Reject malformed declared allowances at load, not at comparison time."""
    for entry in descriptor.get("ignoredLabels") or []:
        _validate_reason(path, "ignoredLabels", entry)
        _reject_unknown_fields(
            path, "ignoredLabels", entry, {"reason", "keys", "podTemplates"}
        )
        keys = entry.get("keys")
        if (
            not isinstance(keys, list)
            or not keys
            or not all(isinstance(key, str) and key for key in keys)
        ):
            raise ValueError(
                f"{path}: an ignoredLabels entry needs a non-empty 'keys' list "
                "of label keys"
            )
        if not isinstance(entry.get("podTemplates", False), bool):
            raise ValueError(f"{path}: ignoredLabels 'podTemplates' must be a boolean")
    for entry in descriptor.get("knownDifferences") or []:
        _validate_reason(path, "knownDifferences", entry)
        fields = set(entry) - {"reason"}
        if "skip" in entry:
            if fields != {"skip"}:
                raise ValueError(
                    f"{path}: a skip entry declares only 'skip' and 'reason'"
                )
            _validate_pattern(path, "skip", entry["skip"])
            continue
        if "resource" not in entry:
            raise ValueError(
                f"{path}: a knownDifferences entry needs 'resource' or 'skip'"
            )
        _validate_pattern(path, "resource", entry["resource"])
        actions = fields - {"resource"}
        unknown = actions - KNOWN_DIFFERENCE_ACTIONS
        if unknown:
            raise ValueError(
                f"{path}: unknown knownDifferences fields: {', '.join(sorted(unknown))}"
            )
        if not actions:
            raise ValueError(
                f"{path}: knownDifferences entry for {entry['resource']!r} declares no action"
            )
        for action in actions:
            value = entry[action]
            if (
                not isinstance(value, list)
                or not value
                or not all(isinstance(item, str) and item for item in value)
            ):
                raise ValueError(f"{path}: {action} must be a non-empty list of keys")
        if "controllerOwnedWebhookRules" in actions:
            segments = entry["resource"].split("/")
            names = entry["controllerOwnedWebhookRules"]
            if (
                actions != {"controllerOwnedWebhookRules"}
                or len(segments) != 2
                or segments[0] not in WEBHOOK_CONFIGURATION_KINDS
                or not EXACT_RESOURCE_NAME.fullmatch(segments[1])
                or any(not EXACT_RESOURCE_NAME.fullmatch(name) for name in names)
                or len(names) != len(set(names))
            ):
                raise ValueError(
                    f"{path}: controllerOwnedWebhookRules must be the only action, "
                    "name an exact MutatingWebhookConfiguration/name or "
                    "ValidatingWebhookConfiguration/name, and list unique exact "
                    "webhook names without wildcard or namespace patterns"
                )

    for entry in descriptor.get("helmOnlyResources") or []:
        _validate_reason(path, "helmOnlyResources", entry)
        _reject_unknown_fields(path, "helmOnlyResources", entry, {"reason", "resource"})
        _validate_pattern(path, "helmOnlyResources", entry.get("resource"))

    retained = descriptor.get("retainedCustomResourceDefinitions")
    if retained is not None:
        _validate_reason(path, "retainedCustomResourceDefinitions", retained)
        _reject_unknown_fields(
            path, "retainedCustomResourceDefinitions", retained, {"reason", "names"}
        )
        names = retained.get("names")
        if not isinstance(names, list) or not names:
            raise ValueError(
                f"{path}: retainedCustomResourceDefinitions needs a non-empty "
                "'names' list"
            )


def load_descriptor(path):
    """Read one descriptor, rejecting the mistakes that used to be possible."""
    descriptor = yaml.load(path.read_text(), Loader=_StrictLoader)
    _reject_unknown_fields(
        path,
        "descriptor",
        descriptor,
        {
            "component",
            "releaseName",
            "namespace",
            "scenarios",
            "defaultScenario",
            "includeCustomResourceDefinitions",
            "helmUsesKustomizeNameHashes",
            "dependencyRepositories",
            "ignoredLabels",
            "knownDifferences",
            "helmOnlyResources",
            "retainedCustomResourceDefinitions",
            "partition",
        },
    )
    for field in ("component", "releaseName", "namespace", "scenarios"):
        if not descriptor.get(field):
            raise ValueError(f"{path}: missing {field!r}")
    _validate_allowances(path, descriptor)
    if "partition" in descriptor:
        _validate_partition(path, descriptor)

    scenarios = descriptor["scenarios"]
    if not isinstance(scenarios, dict):
        raise ValueError(f"{path}: 'scenarios' must be a mapping of name to scenario")
    if len(scenarios) == 1:
        descriptor.setdefault("defaultScenario", next(iter(scenarios)))
    if descriptor.get("defaultScenario") not in scenarios:
        raise ValueError(
            f"{path}: defaultScenario {descriptor.get('defaultScenario')!r} "
            f"is not one of {', '.join(scenarios)}"
        )
    for name, scenario in scenarios.items():
        targets = scenario.get("kustomize") if isinstance(scenario, dict) else None
        if not isinstance(targets, list) or not targets:
            raise ValueError(
                f"{path}: scenario {name!r} must declare a list of Kustomize targets"
            )
        _reject_unknown_fields(
            path,
            f"scenario {name!r}",
            scenario,
            {"kustomize", "values", "onlyKinds", "excludeKinds"},
        )
        if "values" in scenario:
            values = scenario["values"]
            chart_directory = path.parent.parent.resolve()
            if not isinstance(values, str) or not values:
                raise ValueError(
                    f"{path}: scenario {name!r} values must be a non-empty path in the chart"
                )
            values_path = (chart_directory / values).resolve()
            if (
                not values_path.is_relative_to(chart_directory)
                or not values_path.is_file()
            ):
                raise ValueError(
                    f"{path}: scenario {name!r} values file "
                    f"{values!r} does not exist in the chart"
                )
        for field in ("onlyKinds", "excludeKinds"):
            if field in scenario and (
                not isinstance(scenario[field], list) or not scenario[field]
            ):
                raise ValueError(
                    f"{path}: scenario {name!r} field {field!r} must be a "
                    "non-empty list of kinds"
                )
    return descriptor


def _validate_partition(path, descriptor):
    """A chart in a partition group owns exactly a subset of a shared baseline.

    Ownership is proven from the complete rendered output of every member, so
    the allowances that remove or excuse whole objects from an ordinary
    comparison are not available to a member: a skipped or Helm-only object
    would be exactly the unowned or doubly owned object the group must reject.
    """
    group = descriptor["partition"]
    if not isinstance(group, str) or not PARTITION_GROUP_NAME.fullmatch(group):
        # The name also names a working directory, so it is a plain label.
        raise ValueError(
            f"{path}: 'partition' must be a group name of lowercase letters, "
            f"digits and inner hyphens, got {group!r}"
        )
    if any("skip" in entry for entry in descriptor.get("knownDifferences") or []):
        raise ValueError(
            f"{path}: a partition member cannot skip objects; every baseline "
            "object must be owned by exactly one member"
        )
    if descriptor.get("helmOnlyResources"):
        raise ValueError(
            f"{path}: a partition member cannot declare helmOnlyResources; "
            "its release must render exactly its owned baseline subset"
        )


def chart_directories(root=ROOT_DIRECTORY):
    """Every directory the globs name that holds a Chart.yaml."""
    return [
        chart
        for pattern in CHART_GLOBS
        for chart in sorted(root.glob(pattern))
        if (chart / "Chart.yaml").is_file()
    ]


def charts_without_descriptor(root=ROOT_DIRECTORY):
    """Discovery skips a chart with no descriptor, so this guard must not."""
    return [
        chart
        for chart in chart_directories(root)
        if not (chart / "ci" / "comparison.yaml").is_file()
    ]


def discover(root=ROOT_DIRECTORY):
    """Return {component: (chart directory, descriptor)} for every chart."""
    descriptors = {}
    # The same definition of a chart as the coverage guard: a directory with a
    # descriptor but no Chart.yaml is not a chart and is never handed to Helm.
    for chart in chart_directories(root):
        path = chart / "ci" / "comparison.yaml"
        if not path.is_file():
            continue
        descriptor = load_descriptor(path)
        component = descriptor["component"]
        if component in descriptors:
            raise ValueError(f"{component!r} is declared twice: {path}")
        descriptors[component] = (chart, descriptor)
    return descriptors


def render_kustomize(scenario, destination, root=ROOT_DIRECTORY):
    """Concatenate every Kustomize target this scenario compares against."""
    documents = [
        subprocess.run(
            ["kustomize", "build", str(root / path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        for path in scenario["kustomize"]
    ]
    destination.write_text(DOCUMENT_SEPARATOR.join(documents))


def render_helm(chart, descriptor, scenario, destination):
    command = ["helm", "template", descriptor["releaseName"], str(chart)]
    command += ["--namespace", descriptor["namespace"]]
    if descriptor.get("includeCustomResourceDefinitions"):
        command.append("--include-crds")
    if scenario.get("values"):
        command += ["--values", str(chart / scenario["values"])]
    destination.write_text(
        subprocess.run(command, check=True, capture_output=True, text=True).stdout
    )


def compare(component, name, descriptors, rules):
    chart, descriptor = descriptors[component]
    scenario = descriptor["scenarios"][name]
    print(f"Comparing {component} manifests for scenario: {name}")

    try:
        if descriptor.get("dependencyRepositories"):
            for repository, url in descriptor["dependencyRepositories"].items():
                # Adding fails when the repository is already present, and its
                # index may be stale, so refresh it as the previous harness did.
                if subprocess.run(
                    ["helm", "repo", "add", repository, url], capture_output=True
                ).returncode:
                    subprocess.run(
                        ["helm", "repo", "update", repository],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
            subprocess.run(
                ["helm", "dependency", "build", str(chart)],
                check=True,
                capture_output=True,
                text=True,
            )

        with tempfile.TemporaryDirectory() as directory:
            kustomize_output = Path(directory) / "kustomize.yaml"
            helm_output = Path(directory) / "helm.yaml"
            render_kustomize(scenario, kustomize_output)
            render_helm(chart, descriptor, scenario, helm_output)
            return comparator.compare_manifests(
                str(kustomize_output), str(helm_output), rules, scenario
            )
    except subprocess.CalledProcessError as error:
        # Kustomize and Helm explain their own failures; a Python traceback does
        # not. Report the tool's message and let the remaining scenarios run, as
        # the previous aggregate harness did.
        print(f"ERROR: {' '.join(error.cmd)} exited {error.returncode}")
        if error.stderr:
            print(error.stderr.strip())
        return False
    except ValueError as error:
        print(f"ERROR: {error}")
        return False


def partition_groups(descriptors):
    """{group: {component: (chart, descriptor)}} for every declared group."""
    groups = {}
    for component, (chart, descriptor) in sorted(descriptors.items()):
        group = descriptor.get("partition")
        if group is not None:
            groups.setdefault(group, {})[component] = (chart, descriptor)
    return groups


def object_identity(manifest, cluster_scoped):
    """(API group, kind, namespace, name); the namespace is dropped for a kind
    the baseline's own CustomResourceDefinitions declare cluster-scoped, so a
    stray metadata.namespace on such an object cannot split one identity in
    two or hide a duplicate."""
    api_version = manifest.get("apiVersion") or ""
    group = api_version.split("/", maxsplit=1)[0] if "/" in api_version else ""
    kind = manifest.get("kind") or ""
    metadata = manifest.get("metadata") or {}
    name = metadata.get("name") or ""
    if not kind or not name:
        raise ValueError(f"object without kind or metadata.name: {manifest!r:.200}")
    namespace = (
        "" if (group, kind) in cluster_scoped else metadata.get("namespace") or ""
    )
    return group, kind, namespace, name


def cluster_scoped_kinds(manifests):
    """(group, kind) of every custom resource the manifests define as cluster-scoped."""
    return {
        (manifest["spec"]["group"], manifest["spec"]["names"]["kind"])
        for manifest in manifests
        if manifest.get("kind") == "CustomResourceDefinition"
        and (manifest.get("spec") or {}).get("scope") == "Cluster"
    }


def format_identity(identity):
    group, kind, namespace, name = identity
    kind = f"{kind}.{group}" if group else kind
    return f"{kind}/{namespace}/{name}" if namespace else f"{kind}/{name}"


def inventory(manifests, cluster_scoped, source):
    """{identity: manifest}; a repeated identity is an error, never a merge."""
    objects = {}
    problems = []
    for manifest in manifests:
        identity = object_identity(manifest, cluster_scoped)
        if identity in objects:
            problems.append(f"{source} renders {format_identity(identity)} twice")
        objects[identity] = manifest
    return objects, problems


def helm_environment(home):
    """Helm directories under `home`, so dependency builds touch no user state."""
    environment = dict(os.environ)
    for variable in ("HELM_CACHE_HOME", "HELM_CONFIG_HOME", "HELM_DATA_HOME"):
        directory = Path(home) / variable.lower()
        directory.mkdir(parents=True, exist_ok=True)
        environment[variable] = str(directory)
    # These override or extend the home directories, so an inherited value
    # would let the run read or modify the caller's Helm state after all; the
    # storage guard drops the same three.
    for variable in ("HELM_REPOSITORY_CONFIG", "HELM_REPOSITORY_CACHE", "HELM_PLUGINS"):
        environment.pop(variable, None)
    return environment


def prepare_member(chart, descriptor, work, environment):
    """Copy a member chart once and build its dependencies in the copy.

    The copy is what every scenario renders and what the install-once
    inspection reads, so dependencies are resolved exactly once and the
    checkout is never modified; the isolated Helm directories keep repository
    indexes and downloaded archives out of the developer's Helm home.
    """
    copy = Path(work) / chart.name
    shutil.copytree(chart, copy, symlinks=True)
    chart_yaml = yaml.safe_load((copy / "Chart.yaml").read_text()) or {}
    if chart_yaml.get("dependencies"):
        for repository, url in (descriptor.get("dependencyRepositories") or {}).items():
            # Members of one group share the isolated Helm home. Helm 4 accepts
            # a repeated add of the same name and URL, but refuses the same
            # name with another URL; --force-update rewrites the entry and
            # refreshes its index either way, so preparation never aborts on
            # a repository a sibling already added.
            subprocess.run(
                ["helm", "repo", "add", repository, url, "--force-update"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
        subprocess.run(
            ["helm", "dependency", "build", str(copy)],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
    return copy


def install_once_definitions(prepared_chart, environment):
    """Names of the crds/ definitions Helm would install once, at any depth.

    `helm show crds` walks the prepared chart and every dependency, packaged or
    unpacked, and lists only crds/ content, never template-managed definitions.
    """
    shown = subprocess.run(
        ["helm", "show", "crds", str(prepared_chart)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout
    return sorted(
        (document.get("metadata") or {}).get("name") or "<unnamed>"
        for document in yaml.safe_load_all(shown)
        if document
    )


def render_member(prepared_chart, descriptor, scenario, environment):
    """A member release's complete output: nothing filtered, crds/ included.

    Ownership is a property of the release, not of the comparison subset.
    """
    command = ["helm", "template", descriptor["releaseName"], str(prepared_chart)]
    command += ["--namespace", descriptor["namespace"], "--include-crds"]
    if scenario.get("values"):
        command += ["--values", str(prepared_chart / scenario["values"])]
    rendered = subprocess.run(
        command, check=True, capture_output=True, text=True, env=environment
    ).stdout
    return [document for document in yaml.safe_load_all(rendered) if document]


def verify_partition(group, members, root, work):
    """Prove that the members' releases partition their shared baseline.

    The members must declare the same scenarios over the same Kustomize
    targets. For every scenario, each baseline object must be selected by
    exactly one member's kind selection, and each member's complete rendered
    output must be exactly the objects it selects: nothing missing, nothing
    extra, nothing twice. Install-once crds/ content, at any dependency depth,
    and hook-created objects are outside what this contract can prove, so
    they are rejected.
    """
    problems = []
    if len(members) < 2:
        return [f"{group}: a partition group needs at least two charts"]

    scenario_sets = {
        component: frozenset(descriptor["scenarios"])
        for component, (_, descriptor) in members.items()
    }
    if len(set(scenario_sets.values())) != 1:
        return [
            f"{group}: members declare different scenarios: "
            + "; ".join(
                f"{component} {sorted(names)}"
                for component, names in sorted(scenario_sets.items())
            )
        ]

    environment = helm_environment(Path(work) / "helm")
    # Descriptor values name charts and scenarios, never files: working paths
    # are numbered so no descriptor content can reach outside `work`.
    prepared = {}
    for index, (component, (chart, descriptor)) in enumerate(sorted(members.items())):
        prepared[component] = prepare_member(
            chart, descriptor, Path(work) / f"member-{index}", environment
        )
        definitions = install_once_definitions(prepared[component], environment)
        if definitions:
            problems.append(
                f"{group} {component}: install-once crds/ content is not supported "
                "in a partition group; render definitions from templates: "
                + ", ".join(definitions)
            )

    for index, scenario_name in enumerate(sorted(next(iter(scenario_sets.values())))):
        targets = {
            component: tuple(descriptor["scenarios"][scenario_name]["kustomize"])
            for component, (_, descriptor) in members.items()
        }
        if len(set(targets.values())) != 1:
            problems.append(
                f"{group}/{scenario_name}: members compare against different "
                "Kustomize targets: "
                + "; ".join(
                    f"{component} {list(paths)}"
                    for component, paths in sorted(targets.items())
                )
            )
            continue

        baseline_path = Path(work) / f"baseline-{index}.yaml"
        try:
            render_kustomize(
                next(iter(members.values()))[1]["scenarios"][scenario_name],
                baseline_path,
                root,
            )
        except subprocess.CalledProcessError as error:
            problems.append(
                f"{group}/{scenario_name}: {' '.join(error.cmd)} exited "
                f"{error.returncode}: {error.stderr.strip()}"
            )
            continue
        baseline_manifests = comparator.load_manifests(str(baseline_path))
        cluster_scoped = cluster_scoped_kinds(baseline_manifests)
        baseline, baseline_problems = inventory(
            baseline_manifests, cluster_scoped, f"{group}/{scenario_name} baseline"
        )
        problems.extend(baseline_problems)
        if not baseline:
            # Members that render nothing would own nothing and pass; the
            # ordinary comparison rejects an empty selection for the same reason.
            problems.append(
                f"{group}/{scenario_name}: the Kustomize baseline rendered no "
                "objects; nothing to partition"
            )
            continue

        owners = {identity: [] for identity in baseline}
        for component, (chart, descriptor) in sorted(members.items()):
            scenario = descriptor["scenarios"][scenario_name]
            source = f"{group}/{scenario_name} {component}"
            expected = {
                identity
                for identity in baseline
                if comparator.ChartComparisonRules.selects(scenario, identity[1])
            }
            for identity in expected:
                owners[identity].append(component)

            rendered, rendered_problems = inventory(
                render_member(prepared[component], descriptor, scenario, environment),
                cluster_scoped,
                source,
            )
            problems.extend(rendered_problems)
            for identity, manifest in sorted(rendered.items()):
                annotations = (manifest.get("metadata") or {}).get("annotations") or {}
                if HOOK_ANNOTATION in annotations:
                    problems.append(
                        f"{source}: {format_identity(identity)} is a Helm hook; "
                        "hook-created objects are not supported in a partition group"
                    )
            for identity in sorted(expected - set(rendered)):
                problems.append(
                    f"{source}: does not render {format_identity(identity)}, "
                    "which its selection owns"
                )
            for identity in sorted(set(rendered) - expected):
                if identity in baseline:
                    problems.append(
                        f"{source}: renders {format_identity(identity)}, which its "
                        "selection does not own"
                    )
                else:
                    problems.append(
                        f"{source}: renders {format_identity(identity)}, which is "
                        "not in the baseline"
                    )

        for identity, components in sorted(owners.items()):
            if not components:
                problems.append(
                    f"{group}/{scenario_name}: {format_identity(identity)} is owned "
                    "by no member"
                )
            elif len(components) > 1:
                problems.append(
                    f"{group}/{scenario_name}: {format_identity(identity)} is owned "
                    f"by {', '.join(components)}"
                )
    return problems


def verify_partitions(descriptors, root=ROOT_DIRECTORY):
    """Verify every declared partition group; returns the problem lines."""
    problems = []
    with tempfile.TemporaryDirectory() as work:
        for group, members in sorted(partition_groups(descriptors).items()):
            problems.extend(verify_partition(group, members, root, Path(work) / group))
    return problems


def main():
    descriptors = discover()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", nargs="?", help="component to compare, or 'all'")
    parser.add_argument("scenario", nargs="?")
    parser.add_argument(
        "--all-scenarios",
        action="store_true",
        help="compare every scenario the component declares, not just the default",
    )
    parser.add_argument(
        "--list", action="store_true", help="print every component and its scenarios"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="with --list, print the component names as JSON for the CI matrix",
    )
    parser.add_argument(
        "--partitions",
        action="store_true",
        help="verify that every partition group's releases own their shared "
        "baseline exactly once, from their complete rendered output",
    )
    arguments = parser.parse_args()

    if arguments.partitions:
        groups = partition_groups(descriptors)
        if not groups:
            print("No partition groups declared; nothing to verify.")
            return 0
        problems = verify_partitions(descriptors)
        for line in problems:
            print(f"  {line}")
        if problems:
            print(f"FAILED: partition groups {', '.join(sorted(groups))}")
            return 1
        print(
            f"SUCCESS: {len(groups)} partition groups own their baselines exactly "
            f"once: {', '.join(sorted(groups))}"
        )
        return 0

    if arguments.list:
        if arguments.json:
            print(json.dumps(sorted(descriptors)))
            return 0
        for component, (_, descriptor) in sorted(descriptors.items()):
            print(f"{component}: {' '.join(sorted(descriptor['scenarios']))}")
        return 0

    if not arguments.component:
        parser.error("a component is required, or 'all' to compare every component")

    if arguments.component != "all" and arguments.component not in descriptors:
        print(f"ERROR: Unknown component: {arguments.component}")
        print(f"Supported components: {', '.join(sorted(descriptors))}, all")
        return 1

    components = (
        sorted(descriptors) if arguments.component == "all" else [arguments.component]
    )
    failed = []
    for component in components:
        descriptor = descriptors[component][1]
        if arguments.scenario:
            if arguments.scenario not in descriptor["scenarios"]:
                print(f"ERROR: Unknown scenario: {arguments.scenario}")
                print(f"Supported scenarios: {', '.join(descriptor['scenarios'])}")
                return 1
            scenarios = [arguments.scenario]
        elif arguments.component == "all" or arguments.all_scenarios:
            scenarios = sorted(descriptor["scenarios"])
        else:
            scenarios = [descriptor["defaultScenario"]]

        rules = comparator.ChartComparisonRules(descriptor)
        for name in scenarios:
            if not compare(component, name, descriptors, rules):
                print(f"FAILED: {component}/{name}")
                failed.append(f"{component}/{name}")

        # A declared allowance that matches nothing is indistinguishable from
        # one that is wrong, so it fails the run. Only a run that covered every
        # scenario can make that judgement: a resource may exist in one
        # scenario and not another.
        if set(scenarios) == set(descriptor["scenarios"]):
            stale = rules.unfired()
            if stale:
                print(
                    f"Stale comparison allowances for {component}; every "
                    "declared allowance must apply at least once across all "
                    "scenarios:"
                )
                for line in stale:
                    print(f"  {line}")
                print(f"FAILED: {component}/allowances")
                failed.append(f"{component}/allowances")

    if failed:
        print(f"FAILED: {', '.join(failed)}")
        return 1
    print(
        "SUCCESS: All components passed! Helm and Kustomize manifests are equivalent."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
