#!/usr/bin/env python3

import yaml
import sys
import json
from typing import Dict, List, Tuple, Any
import re

KUSTOMIZE_HASH_SUFFIX = re.compile(r"-(?=[a-z0-9]{10}$)[a-z0-9]{10}$")

CERT_MANAGER_KUBEFLOW_RESOURCES = {
    ("ClusterIssuer", "kubeflow-self-signing-issuer"),
    ("NetworkPolicy", "cert-manager-webhook"),
    ("NetworkPolicy", "default-allow-same-namespace-cert-manager"),
}

CERT_MANAGER_KUBEFLOW_LABELS = {
    "app.kubernetes.io/component",
    "app.kubernetes.io/name",
}

DEX_POD_TEMPLATE_CHECKSUM_KEYS = {
    "checksum/config",
    "checksum/oidc-client",
    "checksum/passwords",
}

DASHBOARD_POD_TEMPLATE_CHECKSUM_KEYS = {
    "checksum/config",
}

EXPECTED_HELM_CRD_RESOURCE_POLICIES = {
    "kubeflow-dashboard": {
        "poddefaults.kubeflow.org",
        "profiles.kubeflow.org",
    },
    "kubeflow-notebooks": {
        "notebooks.kubeflow.org",
        "pvcviewers.kubeflow.org",
        "tensorboards.tensorboard.kubeflow.org",
    },
}


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


def validate_helm_crd_resource_policies(
    helm_manifests: List[Dict], component: str
) -> bool:
    """Validate component-specific CRD retention policies before normalization."""
    expected_crds = EXPECTED_HELM_CRD_RESOURCE_POLICIES.get(component)
    if expected_crds is None:
        return True

    retained_crds = {
        manifest.get("metadata", {}).get("name", "")
        for manifest in helm_manifests
        if manifest.get("kind") == "CustomResourceDefinition"
        and manifest.get("metadata", {})
        .get("annotations", {})
        .get("helm.sh/resource-policy")
        == "keep"
    }

    missing_crds = expected_crds - retained_crds
    unexpected_crds = retained_crds - expected_crds

    if missing_crds:
        print(
            "Helm CRDs missing helm.sh/resource-policy=keep: "
            + ", ".join(sorted(missing_crds))
        )
    if unexpected_crds:
        print(
            "Unexpected Helm CRDs with helm.sh/resource-policy=keep: "
            + ", ".join(sorted(unexpected_crds))
        )

    return not missing_crds and not unexpected_crds


def clean_helm_metadata(obj: Any, component: str = "katib") -> Any:
    """Remove Helm-specific metadata that should be ignored in comparison."""
    if isinstance(obj, dict):
        cleaned = {}
        for key, value in obj.items():
            if key == "metadata" and isinstance(value, dict):
                # Clean metadata section
                cleaned_metadata = {}
                for meta_key, meta_value in value.items():
                    if meta_key == "labels" and isinstance(meta_value, dict):
                        # Remove Helm-specific labels (component-specific logic)
                        cleaned_labels = {}
                        for label_key, label_value in meta_value.items():
                            if component == "kubeflow-notebooks":
                                if not label_key.startswith("helm.sh/"):
                                    cleaned_labels[label_key] = label_value
                            elif component == "kserve-models-web-application":
                                # More restrictive filtering for KServe
                                if not label_key.startswith(
                                    ("helm.sh/", "app.kubernetes.io/managed-by")
                                ):
                                    cleaned_labels[label_key] = label_value
                            else:
                                # Standard filtering for Katib and Model Registry
                                helm_labels = [
                                    "app.kubernetes.io/managed-by",
                                    "app.kubernetes.io/version",
                                    "app.kubernetes.io/name",
                                    "app.kubernetes.io/instance",
                                    "app.kubernetes.io/component",
                                ]
                                if (
                                    not label_key.startswith("helm.sh/")
                                    and label_key not in helm_labels
                                ):
                                    cleaned_labels[label_key] = label_value
                        if cleaned_labels:  # Only add if there are remaining labels
                            cleaned_metadata[meta_key] = cleaned_labels
                    elif meta_key == "annotations" and isinstance(meta_value, dict):
                        # Remove only Helm-specific annotations
                        cleaned_annotations = {}
                        for ann_key, ann_value in meta_value.items():
                            if not ann_key.startswith(("helm.sh/", "meta.helm.sh/")):
                                cleaned_annotations[ann_key] = ann_value
                        if (
                            cleaned_annotations
                        ):  # Only add if there are remaining annotations
                            cleaned_metadata[meta_key] = cleaned_annotations
                    else:
                        # Keep all other metadata fields as-is
                        cleaned_metadata[meta_key] = meta_value
                cleaned[key] = cleaned_metadata
            else:
                cleaned[key] = clean_helm_metadata(value, component)
        return cleaned
    elif isinstance(obj, list):
        return [clean_helm_metadata(item, component) for item in obj]
    else:
        return obj


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


def normalize_manifest(
    manifest: Dict, component: str = "katib", normalize_kustomize_names: bool = True
) -> Dict:
    """Normalize manifest by removing/standardizing certain fields."""
    normalized = manifest.copy()

    # Clean Helm-specific metadata
    normalized = clean_helm_metadata(normalized, component)

    if component == "dex":
        remove_dex_pod_template_checksums(normalized)
        normalize_dex_config_map(normalized)

    if component == "kubeflow-dashboard":
        remove_dashboard_pod_template_checksums(normalized)

    if component == "cert-manager":
        preserve_cert_manager_kubeflow_labels(manifest, normalized)

    # Normalize Kustomize hash references only for Kustomize output.
    if normalize_kustomize_names:
        normalized = normalize_kustomize_refs(normalized)

    # Handle ConfigMap data normalization (only for Katib)
    if (
        component == "katib"
        and normalized.get("kind") == "ConfigMap"
        and "data" in normalized
    ):
        data = normalized["data"]
        normalized_data = {}
        for key, value in data.items():
            if isinstance(value, str):
                # Remove leading/trailing whitespace and normalize YAML content
                normalized_value = value.strip()
                # Remove leading --- if present (common in ConfigMap YAML data)
                if normalized_value.startswith("---"):
                    normalized_value = normalized_value[3:].strip()
                normalized_data[key] = normalized_value
            else:
                normalized_data[key] = value
        normalized["data"] = normalized_data

    if (
        normalize_kustomize_names
        and "metadata" in normalized
        and "name" in normalized["metadata"]
    ):
        kind = normalized.get("kind", "")
        if kind in ["Secret", "ConfigMap"]:
            name = normalized["metadata"]["name"]
            normalized["metadata"]["name"] = KUSTOMIZE_HASH_SUFFIX.sub("", name)

    if "metadata" in normalized:
        metadata = normalized["metadata"]

        metadata.pop("generation", None)
        metadata.pop("resourceVersion", None)
        metadata.pop("uid", None)
        metadata.pop("creationTimestamp", None)
        metadata.pop("managedFields", None)

    normalized.pop("status", None)

    def remove_empty_values(obj):
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

    return remove_empty_values(normalized)


def remove_dex_pod_template_checksums(manifest: Dict) -> None:
    """Ignore rollout checksums while preserving other Dex annotations."""
    metadata = manifest.get("metadata", {})
    if (
        manifest.get("kind") != "Deployment"
        or metadata.get("name") != "dex"
        or metadata.get("namespace") != "auth"
    ):
        return

    pod_metadata = manifest.get("spec", {}).get("template", {}).get("metadata", {})
    annotations = pod_metadata.get("annotations")
    if not isinstance(annotations, dict):
        return

    pod_metadata["annotations"] = {
        key: value
        for key, value in annotations.items()
        if key not in DEX_POD_TEMPLATE_CHECKSUM_KEYS
    }


def remove_dashboard_pod_template_checksums(manifest: Dict) -> None:
    """Ignore rollout checksums while preserving other Dashboard annotations.

    The chart names its ConfigMaps without the Kustomize content-hash suffix, so
    it triggers a rollout with a checksum annotation instead. Kustomize achieves
    the same effect through the hashed name and renders no annotation.
    """
    metadata = manifest.get("metadata", {})
    if manifest.get("kind") != "Deployment" or metadata.get("name") not in {
        "dashboard",
        "profiles-deployment",
    }:
        return

    pod_metadata = manifest.get("spec", {}).get("template", {}).get("metadata", {})
    annotations = pod_metadata.get("annotations")
    if not isinstance(annotations, dict):
        return

    pod_metadata["annotations"] = {
        key: value
        for key, value in annotations.items()
        if key not in DASHBOARD_POD_TEMPLATE_CHECKSUM_KEYS
    }


def normalize_dex_config_map(manifest: Dict) -> None:
    """Compare the embedded Dex configuration by YAML value, not quote style."""
    metadata = manifest.get("metadata", {})
    if (
        manifest.get("kind") != "ConfigMap"
        or metadata.get("name") != "dex"
        or metadata.get("namespace") != "auth"
    ):
        return

    config_yaml = manifest.get("data", {}).get("config.yaml")
    if isinstance(config_yaml, str):
        manifest["data"]["config.yaml"] = yaml.safe_load(config_yaml)


def preserve_cert_manager_kubeflow_labels(original: Dict, normalized: Dict) -> None:
    """Keep labels that are intentionally added by cert-manager's Kubeflow overlay."""
    kind = original.get("kind", "")
    name = original.get("metadata", {}).get("name", "")

    if (kind, name) not in CERT_MANAGER_KUBEFLOW_RESOURCES:
        return

    labels = original.get("metadata", {}).get("labels", {})
    preserved_labels = {
        key: value
        for key, value in labels.items()
        if key in CERT_MANAGER_KUBEFLOW_LABELS
    }

    if preserved_labels:
        normalized.setdefault("metadata", {}).setdefault("labels", {}).update(
            preserved_labels
        )


def should_compare_manifest(
    manifest: Dict,
    component: str,
    scenario: str,
    is_kustomize_manifest: bool = True,
) -> bool:
    """Select the resource subset owned by a comparison scenario."""
    kind = manifest.get("kind", "")

    if component in ["cert-manager", "dex", "oauth2-proxy"] and kind == "Namespace":
        return False

    if component == "kubeflow-namespaces" and scenario == "base":
        return kind != "Namespace"

    if component == "kubeflow-namespaces" and scenario == "platform-namespaces":
        return kind == "Namespace"

    if component == "istio" and kind == "Namespace" and is_kustomize_manifest:
        return manifest.get("metadata", {}).get("name", "") != "istio-system"

    return True


def get_resource_key(manifest: Dict, component: str = "katib") -> str:
    """Generate a unique key for the resource."""
    kind = manifest.get("kind", "Unknown")
    name = manifest.get("metadata", {}).get("name", "unknown")
    namespace = manifest.get("metadata", {}).get("namespace", "")

    # The name has already been normalized by normalize_manifest. Stripping the
    # hash suffix a second time here would also remove a legitimate final name
    # segment of exactly ten lowercase alphanumeric characters, for example
    # "dashboard-parameters", and would do so on only one of the two sides.

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


def get_expected_helm_extras(component: str, scenario: str) -> set:
    """Get expected extra resources in Helm for different components and scenarios."""
    if component == "katib":
        return {
            "Secret/kubeflow/katib-webhook-cert",  # Webhook certificates
        }
    elif component == "hub":
        return set()  # No extra resources in Helm for Model Registry
    elif component == "kserve-models-web-application":
        return set()
    elif component in ["cert-manager", "dex", "oauth2-proxy"]:
        return set()
    else:
        return set()


def helm_uses_kustomize_generated_names(component: str) -> bool:
    """Whether the chart reproduces Kustomize's content-hashed resource names.

    Charts that name their ConfigMaps and Secrets without the hash suffix must
    not have that suffix stripped from their side of the comparison, otherwise a
    legitimate final name segment can be removed from one side only.
    """
    return component not in ("oauth2-proxy", "kubeflow-dashboard")


def compare_manifests(
    kustomize_file: str,
    helm_file: str,
    component: str,
    scenario: str,
    namespace: str = "",
    verbose: bool = False,
) -> bool:
    """Compare Kustomize and Helm manifests."""
    kustomize_manifests = load_manifests(kustomize_file)
    helm_manifests = load_manifests(helm_file)

    if not validate_helm_crd_resource_policies(helm_manifests, component):
        return False

    kustomize_resources = {}
    helm_resources = {}

    for manifest in kustomize_manifests:
        if not should_compare_manifest(
            manifest, component, scenario, is_kustomize_manifest=True
        ):
            continue
        normalized = normalize_manifest(
            manifest, component, normalize_kustomize_names=True
        )
        key = get_resource_key(normalized, component)
        kustomize_resources[key] = normalized

    for manifest in helm_manifests:
        if not should_compare_manifest(
            manifest, component, scenario, is_kustomize_manifest=False
        ):
            continue
        normalized = normalize_manifest(
            manifest,
            component,
            normalize_kustomize_names=helm_uses_kustomize_generated_names(component),
        )
        key = get_resource_key(normalized, component)
        helm_resources[key] = normalized

    kustomize_keys = set(kustomize_resources.keys())
    helm_keys = set(helm_resources.keys())

    common_keys = kustomize_keys & helm_keys
    only_in_kustomize = kustomize_keys - helm_keys
    only_in_helm = helm_keys - kustomize_keys

    expected_helm_extras = get_expected_helm_extras(component, scenario)
    unexpected_helm_extras = only_in_helm - expected_helm_extras

    differences_found = []
    success = True

    if only_in_kustomize:
        print(f"Resources only in Kustomize: {len(only_in_kustomize)}")
        if verbose:
            for key in sorted(only_in_kustomize):
                print(f"  {key}")
        success = False
        differences_found.extend(only_in_kustomize)

    if unexpected_helm_extras:
        print(f"Unexpected resources only in Helm: {len(unexpected_helm_extras)}")
        if verbose:
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
            if verbose:
                for difference in differences:
                    print(f"  {difference}")
            differences_found.append(key)
            success = False

    if not success:
        print(f"Found differences in {len(differences_found)} resources")
        return False

    return True


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print(
            "Usage: python helm_kustomize_compare.py <kustomize_file> <helm_file> <component> <scenario> [namespace] [--verbose]"
        )
        print(
            "Components: katib, hub, kserve-models-web-application, cert-manager, kubeflow-namespaces, kubeflow-platform, dex, oauth2-proxy, istio, kubeflow-dashboard, kubeflow-notebooks"
        )
        sys.exit(1)

    kustomize_file = sys.argv[1]
    helm_file = sys.argv[2]
    component = sys.argv[3]
    scenario = sys.argv[4]
    namespace = (
        sys.argv[5] if len(sys.argv) > 5 and not sys.argv[5].startswith("--") else ""
    )

    if component not in [
        "katib",
        "hub",
        "kserve-models-web-application",
        "cert-manager",
        "kubeflow-namespaces",
        "kubeflow-platform",
        "dex",
        "oauth2-proxy",
        "istio",
        "kubeflow-dashboard",
        "kubeflow-notebooks",
    ]:
        print(f"ERROR: Unknown component: {component}")
        print(
            "Supported components: katib, hub, kserve-models-web-application, cert-manager, kubeflow-namespaces, kubeflow-platform, dex, oauth2-proxy, istio, kubeflow-dashboard, kubeflow-notebooks"
        )
        sys.exit(1)

    verbose = "--verbose" in sys.argv[1:]

    success = compare_manifests(
        kustomize_file, helm_file, component, scenario, namespace, verbose
    )
    sys.exit(0 if success else 1)
