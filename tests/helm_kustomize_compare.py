#!/usr/bin/env python3
"""Decide whether two rendered manifest sets describe the same resources.

Invoked by tests/run_helm_kustomize_comparison.py, which discovers components,
renders both sides and loads each chart's descriptor. This module knows about
Kubernetes resources; that one knows about files and processes.

Only universal facts about the two renderers are normalized here in code: the
helm.sh label and annotation namespaces, and Kustomize's content-hash suffixes,
stripped from the Helm side only when the chart reproduces them. Everything
specific to one chart is declared in that chart's ci/comparison.yaml, carries a
validated reason, and is reported as stale when it stops matching anything.
"""

import fnmatch
import re
from typing import Any, Dict, List

import yaml

KUSTOMIZE_HASH_SUFFIX = re.compile(r"-(?=[a-z0-9]{10}$)[a-z0-9]{10}$")
HELM_LABEL_PREFIX = "helm.sh/"
HELM_ANNOTATION_PREFIXES = ("helm.sh/", "meta.helm.sh/")


def load_manifests(file_path: str) -> List[Dict]:
    """Load YAML manifests from file."""
    with open(file_path, "r") as f:
        content = f.read()

    docs = []
    try:
        for doc in yaml.safe_load_all(content):
            if doc:
                docs.append(doc)
    except yaml.YAMLError:
        for doc_str in content.split("---"):
            doc_str = doc_str.strip()
            if doc_str:
                try:
                    doc = yaml.safe_load(doc_str)
                    if doc:
                        docs.append(doc)
                except yaml.YAMLError:
                    continue

    return docs


def resource_matches(pattern: str, kind: str, namespace: str, name: str) -> bool:
    """Match a 'Kind/name' or 'Kind/namespace/name' pattern with * wildcards.

    A two-segment pattern matches the kind and name in any namespace, which is
    how cluster-scoped resources are named.
    """
    segments = pattern.split("/")
    if len(segments) == 2:
        return fnmatch.fnmatchcase(kind, segments[0]) and fnmatch.fnmatchcase(
            name, segments[1]
        )
    return (
        fnmatch.fnmatchcase(kind, segments[0])
        and fnmatch.fnmatchcase(namespace, segments[1])
        and fnmatch.fnmatchcase(name, segments[2])
    )


# Kinds that never carry a namespace, so a release namespace must not be
# applied to them.
CLUSTER_SCOPED_KINDS = {
    "APIService",
    "ClusterIssuer",
    "ClusterRole",
    "ClusterRoleBinding",
    "CustomResourceDefinition",
    "IngressClass",
    "MutatingWebhookConfiguration",
    "Namespace",
    "PersistentVolume",
    "PriorityClass",
    "StorageClass",
    "ValidatingAdmissionPolicy",
    "ValidatingAdmissionPolicyBinding",
    "ValidatingWebhookConfiguration",
}


class ChartComparisonRules:
    """Interpret one chart's declared comparison allowances.

    Reuse a single instance across every scenario of a component: each
    allowance must apply to at least one resource in at least one scenario,
    and unfired() reports the ones that never did. An allowance that matches
    nothing is indistinguishable from one that is wrong, so the caller treats
    a non-empty unfired() as a failure.
    """

    def __init__(self, descriptor: Dict):
        self.ignored_labels = descriptor.get("ignoredLabels") or []
        self.known_differences = descriptor.get("knownDifferences") or []
        self.retained_custom_resource_definitions = set(
            (descriptor.get("retainedCustomResourceDefinitions") or {}).get("names")
            or []
        )
        self.helm_only_resources = descriptor.get("helmOnlyResources") or []
        self.helm_uses_kustomize_name_hashes = descriptor.get(
            "helmUsesKustomizeNameHashes", True
        )
        self.helm_release_namespace = (
            descriptor.get("namespace", "")
            if descriptor.get("helmUsesReleaseNamespace")
            else ""
        )
        self._fired = set()

    def should_compare(self, manifest: Dict, scenario: Dict) -> bool:
        """Select the resource subset owned by a comparison scenario."""
        kind = manifest.get("kind", "")
        metadata = manifest.get("metadata", {})
        namespace = metadata.get("namespace", "")
        name = metadata.get("name", "")

        only_kinds = scenario.get("onlyKinds")
        if only_kinds is not None and kind not in only_kinds:
            return False
        if kind in (scenario.get("excludeKinds") or []):
            return False

        for index, entry in enumerate(self.known_differences):
            pattern = entry.get("skip")
            if pattern and resource_matches(pattern, kind, namespace, name):
                self._fired.add(f"knownDifferences[{index}]")
                return False
        return True

    def normalize(self, manifest: Dict, is_helm_manifest: bool) -> Dict:
        """Normalize one manifest according to universal and declared rules."""
        kind = manifest.get("kind", "")
        metadata = manifest.get("metadata", {})
        namespace = metadata.get("namespace", "")
        name = metadata.get("name", "")

        normalized = self._strip_ignored_metadata(manifest)
        self._apply_known_differences(normalized, kind, namespace, name)

        # Kustomize appends a ten-character content hash to generated ConfigMap
        # and Secret names and to every reference to them. The Helm side is only
        # normalized when the chart reproduces those hashed names; stripping a
        # hash the chart never adds would truncate a legitimate name segment.
        if not is_helm_manifest or self.helm_uses_kustomize_name_hashes:
            normalized = normalize_kustomize_refs(normalized)
            if normalized.get("kind") in ("Secret", "ConfigMap"):
                name_value = normalized.get("metadata", {}).get("name")
                if isinstance(name_value, str):
                    normalized["metadata"]["name"] = KUSTOMIZE_HASH_SUFFIX.sub(
                        "", name_value
                    )

        # A chart that declares helmUsesReleaseNamespace omits
        # metadata.namespace and relies on the release namespace instead; the
        # resource still lands there. Kustomize writes the field through its
        # namespace transformer, so without this the two sides key the same
        # object differently and each reports the other's copy as missing.
        if (
            is_helm_manifest
            and self.helm_release_namespace
            and kind not in CLUSTER_SCOPED_KINDS
        ):
            normalized.setdefault("metadata", {}).setdefault(
                "namespace", self.helm_release_namespace
            )

        return remove_empty_values(normalized)

    def validate_retained_custom_resource_definitions(
        self, helm_manifests: List[Dict]
    ) -> bool:
        """Every keep-annotated CustomResourceDefinition must be declared.

        The keep annotation freezes a CustomResourceDefinition's lifecycle:
        helm uninstall leaves it behind. That behavior must be a declared,
        reviewed property of the chart, never a silent one.
        """
        retained = {
            manifest.get("metadata", {}).get("name", "")
            for manifest in helm_manifests
            if manifest.get("kind") == "CustomResourceDefinition"
            and manifest.get("metadata", {})
            .get("annotations", {})
            .get("helm.sh/resource-policy")
            == "keep"
        }
        for name in retained & self.retained_custom_resource_definitions:
            self._fired.add(f"retainedCustomResourceDefinitions[{name}]")

        unexpected = retained - self.retained_custom_resource_definitions
        if unexpected:
            print(
                "CustomResourceDefinitions with helm.sh/resource-policy=keep "
                "that are not declared in retainedCustomResourceDefinitions: "
                + ", ".join(sorted(unexpected))
            )
        return not unexpected

    def unexpected_helm_only(self, only_in_helm: set) -> set:
        """Filter Helm-side extras down to the undeclared ones."""
        unexpected = set()
        for key in only_in_helm:
            segments = key.split("/")
            kind, namespace, name = (
                segments if len(segments) == 3 else (segments[0], "", segments[1])
            )
            for index, entry in enumerate(self.helm_only_resources):
                if resource_matches(entry["resource"], kind, namespace, name):
                    self._fired.add(f"helmOnlyResources[{index}]")
                    break
            else:
                unexpected.add(key)
        return unexpected

    def unfired(self) -> List[str]:
        """Describe every declared allowance that matched nothing."""
        report = []
        for index, entry in enumerate(self.ignored_labels):
            if f"ignoredLabels[{index}]" not in self._fired:
                report.append(f"ignoredLabels: {', '.join(entry['keys'])}")
        for index, entry in enumerate(self.known_differences):
            if f"knownDifferences[{index}]" not in self._fired:
                report.append(
                    f"knownDifferences: {entry.get('resource') or entry.get('skip')}"
                )
        for name in sorted(self.retained_custom_resource_definitions):
            if f"retainedCustomResourceDefinitions[{name}]" not in self._fired:
                report.append(f"retainedCustomResourceDefinitions: {name}")
        for index, entry in enumerate(self.helm_only_resources):
            if f"helmOnlyResources[{index}]" not in self._fired:
                report.append(f"helmOnlyResources: {entry['resource']}")
        return report

    def _ignored_label_entries(self, top_level: bool) -> List[int]:
        """Indices of ignoredLabels entries applying at this metadata block.

        An entry applies to every resource's own metadata; nested template
        metadata is compared strictly unless the entry declares podTemplates,
        for a chart that also adds the keys to its workloads' pod templates.
        """
        return [
            index
            for index, entry in enumerate(self.ignored_labels)
            if top_level or entry.get("podTemplates")
        ]

    def _strip_ignored_metadata(self, manifest: Dict) -> Dict:
        """Rebuild the manifest without ignored labels and Helm annotations.

        Helm's own label and annotation namespaces are stripped from every
        metadata mapping; declared ignoredLabels apply per entry, to top-level
        metadata by default.
        """

        def clean_metadata(block: Dict, entry_indices: List[int]) -> Dict:
            cleaned = {}
            for key, value in block.items():
                if key == "labels" and isinstance(value, dict):
                    kept = {}
                    for label_key, label_value in value.items():
                        if label_key.startswith(HELM_LABEL_PREFIX):
                            continue
                        owners = [
                            index
                            for index in entry_indices
                            if label_key in self.ignored_labels[index]["keys"]
                        ]
                        if owners:
                            for index in owners:
                                self._fired.add(f"ignoredLabels[{index}]")
                            continue
                        kept[label_key] = label_value
                    if kept:
                        cleaned[key] = kept
                elif key == "annotations" and isinstance(value, dict):
                    kept = {
                        annotation_key: annotation_value
                        for annotation_key, annotation_value in value.items()
                        if not annotation_key.startswith(HELM_ANNOTATION_PREFIXES)
                    }
                    if kept:
                        cleaned[key] = kept
                else:
                    cleaned[key] = value
            return cleaned

        def walk(obj: Any, at_resource_root: bool) -> Any:
            if isinstance(obj, dict):
                result = {}
                for key, value in obj.items():
                    if key == "metadata" and isinstance(value, dict):
                        indices = self._ignored_label_entries(at_resource_root)
                        result[key] = clean_metadata(value, indices)
                    else:
                        result[key] = walk(value, False)
                return result
            if isinstance(obj, list):
                return [walk(item, False) for item in obj]
            return obj

        return walk(manifest, True)

    def _apply_known_differences(
        self, normalized: Dict, kind: str, namespace: str, name: str
    ) -> None:
        for index, entry in enumerate(self.known_differences):
            pattern = entry.get("resource")
            if not pattern or not resource_matches(pattern, kind, namespace, name):
                continue
            identity = f"knownDifferences[{index}]"

            ignored_annotations = entry.get("ignorePodTemplateAnnotations")
            if ignored_annotations:
                annotations = (
                    normalized.get("spec", {})
                    .get("template", {})
                    .get("metadata", {})
                    .get("annotations")
                )
                if isinstance(annotations, dict):
                    kept = {
                        key: value
                        for key, value in annotations.items()
                        if key not in set(ignored_annotations)
                    }
                    if kept != annotations:
                        self._fired.add(identity)
                        normalized["spec"]["template"]["metadata"]["annotations"] = kept

            for data_key in entry.get("compareDataAsYaml") or []:
                value = normalized.get("data", {}).get(data_key)
                if isinstance(value, str):
                    normalized["data"][data_key] = yaml.safe_load(value)
                    self._fired.add(identity)


def normalize_kustomize_refs(obj: Any, path: str = "") -> Any:
    """Normalize Kustomize hash suffixes in secret/configmap references throughout the manifest."""
    if isinstance(obj, dict):
        normalized = {}
        for key, value in obj.items():
            current_path = f"{path}.{key}" if path else key

            # Normalize secret/configmap references in common locations
            if isinstance(value, str):
                if key == "name" and any(
                    ref_pattern in path
                    for ref_pattern in [
                        "secretKeyRef",
                        "configMapKeyRef",
                        "configMapRef",
                        "secret",
                        "volumes",
                    ]
                ):
                    value = KUSTOMIZE_HASH_SUFFIX.sub("", value)
                elif key == "secretName" and "volumes" in path:
                    value = KUSTOMIZE_HASH_SUFFIX.sub("", value)
                elif key == "name" and "volumes" in path and "configMap" in path:
                    value = KUSTOMIZE_HASH_SUFFIX.sub("", value)

            normalized[key] = normalize_kustomize_refs(value, current_path)
        return normalized
    elif isinstance(obj, list):
        return [normalize_kustomize_refs(item, path) for item in obj]
    else:
        return obj


def remove_empty_values(obj: Any) -> Any:
    """Drop None, empty mappings and empty lists everywhere."""
    if isinstance(obj, dict):
        return {
            k: remove_empty_values(v)
            for k, v in obj.items()
            if v is not None and v != {} and v != []
        }
    elif isinstance(obj, list):
        return [remove_empty_values(item) for item in obj if item is not None]
    else:
        return obj


def get_resource_key(manifest: Dict) -> str:
    """Generate a unique key for the resource."""
    kind = manifest.get("kind", "Unknown")
    name = manifest.get("metadata", {}).get("name", "unknown")
    namespace = manifest.get("metadata", {}).get("namespace", "")

    # The name has already been normalized by ChartComparisonRules.normalize.
    # Stripping the hash suffix a second time here would also remove a
    # legitimate final name segment of exactly ten lowercase alphanumeric
    # characters, for example "dashboard-parameters", and would do so on only
    # one of the two sides.

    # Include namespace for namespaced resources so same-name objects in
    # different namespaces cannot overwrite each other in the comparison map.
    if namespace:
        return f"{kind}/{namespace}/{name}"
    else:
        return f"{kind}/{name}"


def deep_diff(obj1: Any, obj2: Any, path: str = "") -> List[str]:
    """Compare two objects and return list of differences."""
    differences = []

    if type(obj1) != type(obj2):
        differences.append(
            f"{path}: type mismatch ({type(obj1).__name__} vs {type(obj2).__name__})"
        )
        return differences

    if isinstance(obj1, dict):
        all_keys = set(obj1.keys()) | set(obj2.keys())
        for key in sorted(all_keys):
            key_path = f"{path}.{key}" if path else key
            if key not in obj1:
                differences.append(f"{key_path}: missing in kustomize")
            elif key not in obj2:
                differences.append(f"{key_path}: missing in helm")
            else:
                differences.extend(deep_diff(obj1[key], obj2[key], key_path))

    elif isinstance(obj1, list):
        if len(obj1) != len(obj2):
            differences.append(
                f"{path}: list length mismatch ({len(obj1)} vs {len(obj2)})"
            )
        else:
            for i, (item1, item2) in enumerate(zip(obj1, obj2)):
                differences.extend(deep_diff(item1, item2, f"{path}[{i}]"))

    elif obj1 != obj2:
        differences.append(f"{path}: '{obj1}' != '{obj2}'")

    return differences


def compare_manifests(
    kustomize_file: str,
    helm_file: str,
    rules: ChartComparisonRules,
    scenario: Dict,
) -> bool:
    """Compare Kustomize and Helm manifests under one chart's declared rules."""
    kustomize_manifests = load_manifests(kustomize_file)
    helm_manifests = load_manifests(helm_file)

    if not rules.validate_retained_custom_resource_definitions(helm_manifests):
        return False

    kustomize_resources = {}
    helm_resources = {}

    for manifest in kustomize_manifests:
        if not rules.should_compare(manifest, scenario):
            continue
        normalized = rules.normalize(manifest, is_helm_manifest=False)
        kustomize_resources[get_resource_key(normalized)] = normalized

    for manifest in helm_manifests:
        if not rules.should_compare(manifest, scenario):
            continue
        normalized = rules.normalize(manifest, is_helm_manifest=True)
        helm_resources[get_resource_key(normalized)] = normalized

    # A misspelled onlyKinds or excludeKinds filter selects nothing on either
    # side, and two empty sets compare equal; that is a coverage failure, not
    # a parity success.
    if not kustomize_resources and not helm_resources:
        print("Scenario selection left nothing to compare on either side")
        return False

    kustomize_keys = set(kustomize_resources.keys())
    helm_keys = set(helm_resources.keys())

    common_keys = kustomize_keys & helm_keys
    only_in_kustomize = kustomize_keys - helm_keys
    only_in_helm = helm_keys - kustomize_keys

    unexpected_helm_extras = rules.unexpected_helm_only(only_in_helm)

    differences_found = []
    success = True

    if only_in_kustomize:
        print(f"Resources only in Kustomize: {len(only_in_kustomize)}")
        for key in sorted(only_in_kustomize):
            print(f"  {key}")
        success = False
        differences_found.extend(only_in_kustomize)

    if unexpected_helm_extras:
        print(f"Unexpected resources only in Helm: {len(unexpected_helm_extras)}")
        for key in sorted(unexpected_helm_extras):
            print(f"  {key}")
        success = False
        differences_found.extend(unexpected_helm_extras)

    # Compare common resources
    for key in sorted(common_keys):
        kustomize_resource = kustomize_resources[key]
        helm_resource = helm_resources[key]

        differences = deep_diff(kustomize_resource, helm_resource)

        if differences:
            print(f"Differences in {key}: {len(differences)} fields")
            for difference in differences:
                print(f"  {difference}")
            differences_found.append(key)
            success = False

    if not success:
        print(f"Found differences in {len(differences_found)} resources")
        return False

    return True
