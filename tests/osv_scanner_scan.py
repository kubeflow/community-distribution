# The script:
# 1. Extract all the images used by the Kubeflow Working Groups
# - The reported image lists are saved in respective files under ../image_lists directory
# 2. Scan the reported images using osv-scanner for security vulnerabilities
# - Scanned reports will be saved in JSON format inside ../image_lists/security_scan_reports/ folder for each Working Group
# 3. The script will also generate a summary of the security scan reports with severity counts for each Working Group with images
# - Summary of security counts with images a JSON file inside ../image_lists/summary_of_severity_counts_for_WG folder
# 4. Generate a summary of the security scan reports
# - The summary will be saved in JSON format inside ../image_lists/summary_of_severity_counts_for_WG folder
# The script must be executed from the tests/ folder as it uses relative paths

import os
import subprocess
import re
import argparse
import json
import glob
from prettytable import PrettyTable


def get_osv_scanner_binary():
    """Locate the osv-scanner binary in known installation directories."""
    for directory in ["/tmp/usr/local/bin", os.path.expandvars("$HOME/.local/bin")]:
        osv_scanner_path = os.path.join(directory, "osv-scanner")
        if os.path.isfile(osv_scanner_path):
            return osv_scanner_path
    return "osv-scanner"


# Dictionary mapping Kubeflow workgroups to directories containing kustomization files
working_group_directories = {
    "katib": [
        "../applications/katib/upstream/installs",
    ],
    "pipelines": [
        "../applications/pipeline/upstream/env/cert-manager/platform-agnostic-multi-user",
    ],
    "trainer": [
        "../applications/trainer/overlays",
        "../applications/training-operator/upstream/overlays",
    ],
    "manifests": [
        "../common/cert-manager/overlays/kubeflow",
        "../common/dex/overlays/oauth2-proxy",
        "../common/istio/cluster-local-gateway/base",
        "../common/istio/istio-crds/base",
        "../common/istio/istio-install/overlays/oauth2-proxy",
        "../common/istio/istio-namespace/base",
        "../common/istio/kubeflow-istio-resources/base",
        "../common/knative/knative-eventing/base",
        "../common/knative/knative-serving/overlays/gateways",
        "../common/kubeflow-namespace/base",
        "../common/kubeflow-roles/base",
        "../common/oauth2-proxy/overlays/m2m-dex-and-kind",
        "../common/oauth2-proxy/overlays/m2m-dex-only",
    ],
    "workspaces": [
        # kubeflow/dashboard
        "../applications/dashboard/upstream/centraldashboard/overlays",
        "../applications/dashboard/upstream/poddefaults-webhooks/overlays",
        "../applications/dashboard/upstream/profile-controller/overlays",
        # kubeflow/notebooks
        "../applications/notebooks-v1/upstream",
    ],
    "kserve": [
        "../applications/kserve",
        "../applications/kserve/kserve-ui/upstream/overlays/kubeflow",
    ],
    "hub": [
        "../applications/hub/upstream/options/istio",
        "../applications/hub/upstream/options/ui/overlays/istio",
        "../applications/hub/upstream/overlays/db",
    ],
    "spark": [
        "../applications/spark/spark-operator/overlays/kubeflow",
    ],
}

DIRECTORY = "../image_lists"
os.makedirs(DIRECTORY, exist_ok=True)
SCAN_REPORTS_DIR = os.path.join(DIRECTORY, "security_scan_reports")
ALL_SEVERITY_COUNTS = os.path.join(DIRECTORY, "severity_counts_with_images_for_WG")
SUMMARY_OF_SEVERITY_COUNTS = os.path.join(
    DIRECTORY, "summary_of_severity_counts_for_WG"
)

os.makedirs(SCAN_REPORTS_DIR, exist_ok=True)
os.makedirs(ALL_SEVERITY_COUNTS, exist_ok=True)
os.makedirs(SUMMARY_OF_SEVERITY_COUNTS, exist_ok=True)


def log(*args, **kwargs):
    # Custom log function that print messages with flush=True by default.
    kwargs.setdefault("flush", True)
    print(*args, **kwargs)


def save_images(working_group, images, version):
    """Save a list of container images to a text file named after the workgroup and version."""
    output_file = f"../image_lists/kf_{version}_{working_group}_images.txt"
    with open(output_file, "w") as file_handle:
        file_handle.write("\n".join(images))
    log(f"File {output_file} successfully created")


def validate_semantic_version(version):
    """Validate a semantic version string (e.g., '0.1.2' or 'latest')."""
    regex = r"^[0-9]+\.[0-9]+\.[0-9]+$"
    if re.match(regex, version) or version == "latest":
        return version
    else:
        raise ValueError(f"Invalid semantic version: '{version}'")


def classify_severity_from_cvss_score(cvss_score_string):
    """Classify a numeric CVSS score string into a categorical severity level.

    CVSS v3 score ranges (NIST NVD standard):
      9.0 - 10.0 → CRITICAL
      7.0 -  8.9 → HIGH
      4.0 -  6.9 → MEDIUM
      0.1 -  3.9 → LOW
      0.0        → NONE (treated as UNKNOWN)
    """
    try:
        score = float(cvss_score_string)
    except (ValueError, TypeError):
        return "UNKNOWN"
    if score >= 9.0:
        return "CRITICAL"
    elif score >= 7.0:
        return "HIGH"
    elif score >= 4.0:
        return "MEDIUM"
    elif score > 0.0:
        return "LOW"
    return "UNKNOWN"


def extract_severity_counts_from_osv_json(scan_data):
    """Extract severity counts from osv-scanner JSON output.

    Iterates over vulnerability groups (which deduplicate aliases such as
    CVE and GHSA entries for the same vulnerability) and classifies each
    group by its max_severity CVSS score.

    Returns a dict with keys LOW, MEDIUM, HIGH, CRITICAL and integer counts.
    Returns None if no vulnerability data is present.
    """
    severity_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    has_vulnerabilities = False

    for result in scan_data.get("results", []):
        for package_entry in result.get("packages", []):
            for group in package_entry.get("groups", []):
                max_severity_value = group.get("max_severity", "")
                severity = classify_severity_from_cvss_score(max_severity_value)
                if severity == "UNKNOWN":
                    continue
                severity_counts[severity] += 1
                has_vulnerabilities = True

    if not has_vulnerabilities:
        return None
    return severity_counts


def extract_images(version):
    """Extract container images from kustomize manifests for all working groups."""
    version = validate_semantic_version(version)
    log(f"Running the script using Kubeflow version: {version}")

    all_images = set()  # Collect all unique images across workgroups

    for working_group, directories in working_group_directories.items():
        working_group_images = set()  # Collect unique images for this workgroup
        for directory_path in directories:
            for root, _, files in os.walk(directory_path):
                for file in files:
                    if file in [
                        "kustomization.yaml",
                        "kustomization.yml",
                        "Kustomization",
                    ]:
                        try:
                            # Execute `kustomize build` to render the kustomization file
                            result = subprocess.run(
                                ["kustomize", "build", root],
                                check=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                            )
                        except subprocess.CalledProcessError:
                            log(
                                f'ERROR:\t Failed "kustomize build" command for directory: {root}. See error above'
                            )
                            continue

                        # Use regex to find lines with 'image: <image-name>:<version>' or 'image: <image-name>'
                        # and '- image: <image-name>:<version>' but avoid environment variables
                        kustomize_images = re.findall(
                            r"^\s*-?\s*image:\s*([^$\s:]+(?:\:[^\s]+)?)$",
                            result.stdout,
                            re.MULTILINE,
                        )
                        working_group_images.update(kustomize_images)

        # Ensure uniqueness within workgroup images
        unique_working_group_images = sorted(working_group_images)
        all_images.update(unique_working_group_images)
        save_images(working_group, unique_working_group_images, version)

    # Ensure uniqueness across all workgroups
    unique_images = sorted(all_images)
    save_images("all", unique_images, version)


parser = argparse.ArgumentParser(
    description="Extract images from Kubeflow kustomizations."
)
# Define a positional argument 'version' with optional occurrence and default value 'latest'. You can run this file as python3 <filename>.py or python <filename>.py <version>
parser.add_argument(
    "version",
    nargs="?",
    type=str,
    default="latest",
    help="Kubeflow version to use (defaults to latest).",
)
args = parser.parse_args()
extract_images(args.version)


log("Started scanning images")

# Get list of text files excluding "kf_latest_all_images.txt"
files = [
    f
    for f in glob.glob(os.path.join(DIRECTORY, "*.txt"))
    if not f.endswith("kf_latest_all_images.txt")
]

# Loop through each text file in the specified directory
for file in files:
    log(f"Scanning images in {file}")

    file_base_name = os.path.basename(file).replace(".txt", "")

    # Directory to save reports for this specific file
    file_reports_dir = os.path.join(SCAN_REPORTS_DIR, file_base_name)
    os.makedirs(file_reports_dir, exist_ok=True)

    # Directory to save security count
    severity_count = os.path.join(file_reports_dir, "severity_counts")
    os.makedirs(severity_count, exist_ok=True)

    with open(file, "r") as file_handle:
        lines = file_handle.readlines()

    for line in lines:
        line = line.strip()
        image_name = line.split(":")[0]
        image_tag = line.split(":")[1] if ":" in line else ""

        image_name_scan = image_name.split("/")[-1]

        if image_tag:
            image_name_scan = f"{image_name_scan}_{image_tag}"

        scan_output_file = os.path.join(
            file_reports_dir, f"{image_name_scan}_scan.json"
        )

        log(f"Scanning ", line)

        try:
            # osv-scanner exits with code 1 when vulnerabilities are found,
            # code 0 when clean, and code > 1 on error. Do not use check=True
            # because exit code 1 is a normal "vulnerabilities found" result.
            result = subprocess.run(
                [
                    get_osv_scanner_binary(),
                    "scan",
                    "image",
                    line,
                    "--format",
                    "json",
                    "--output",
                    scan_output_file,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            if result.returncode > 1:
                log(f"Error scanning {image_name}:{image_tag}")
                log(result.stderr)
                continue

            if not os.path.isfile(scan_output_file):
                log(f"No scan output file generated for {image_name}:{image_tag}")
                continue

            with open(scan_output_file, "r") as json_file:
                scan_data = json.load(json_file)

            severity_counts = extract_severity_counts_from_osv_json(scan_data)

            if severity_counts is None:
                log(f"No vulnerabilities found in {image_name}:{image_tag}")
            else:
                report = {"image": line, "severity_counts": severity_counts}

                image_table = PrettyTable()
                image_table.field_names = ["Critical", "High", "Medium", "Low"]
                image_table.add_row(
                    [
                        severity_counts["CRITICAL"],
                        severity_counts["HIGH"],
                        severity_counts["MEDIUM"],
                        severity_counts["LOW"],
                    ]
                )
                log(f"{image_table}\n")

                severity_report_file = os.path.join(
                    severity_count, f"{image_name_scan}_severity_report.json"
                )
                with open(severity_report_file, "w") as report_file:
                    json.dump(report, report_file, indent=4)

        except Exception as scan_error:
            log(f"Error scanning {image_name}:{image_tag}: {scan_error}")

    # Combine all the JSON files into a single file with severity counts for all images
    json_files = glob.glob(os.path.join(severity_count, "*.json"))

    output_file = os.path.join(ALL_SEVERITY_COUNTS, f"{file_base_name}.json")

    if not json_files:
        log(f"No JSON files found in '{severity_count}'. Skipping combination.")
    else:
        combined_data = []
        for json_file in json_files:
            with open(json_file, "r") as json_file_handle:
                combined_data.append(json.load(json_file_handle))

        with open(output_file, "w") as output_file_handle:
            json.dump({"data": combined_data}, output_file_handle, indent=4)

        log(f"JSON files successfully combined into '{output_file}'")

# File to save summary of the severity counts for WGs as JSON format.
summary_file = os.path.join(
    SUMMARY_OF_SEVERITY_COUNTS, "severity_summary_in_json_format.json"
)

# Initialize counters
unique_images = {}  # unique set of images across all WGs
total_images = 0
total_low = 0
total_medium = 0
total_high = 0
total_critical = 0

# Initialize a dictionary to hold the final JSON data
merged_data = {}

# Loop through each JSON file in the ALL_SEVERITY_COUNTS
for file_path in glob.glob(os.path.join(ALL_SEVERITY_COUNTS, "*.json")):
    # Split filename based on underscores
    filename_parts = os.path.basename(file_path).split("_")

    # Check if there are at least 3 parts (prefix, name, _images)
    if len(filename_parts) >= 4:
        # Extract name (second part)
        filename = filename_parts[2]
        filename = filename.capitalize()

    else:
        log(f"Skipping invalid filename format: {file_path}")
        continue

    with open(file_path, "r") as file_handle:
        data = json.load(file_handle)["data"]

    # Initialize counts for this file
    image_count = len(data)
    low = sum(entry["severity_counts"]["LOW"] for entry in data)
    medium = sum(entry["severity_counts"]["MEDIUM"] for entry in data)
    high = sum(entry["severity_counts"]["HIGH"] for entry in data)
    critical = sum(entry["severity_counts"]["CRITICAL"] for entry in data)

    # Update unique_images for the total counts later
    for d in data:
        unique_images[d["image"]] = d

    # Create the output for this file
    file_data = {
        "images": image_count,
        "LOW": low,
        "MEDIUM": medium,
        "HIGH": high,
        "CRITICAL": critical,
    }

    # Update merged_data with filename as key
    merged_data[filename] = file_data


# Update the total counts
unique_images = unique_images.values()  # keep the set of values
total_images += len(unique_images)
total_low += sum(entry["severity_counts"]["LOW"] for entry in unique_images)
total_medium += sum(entry["severity_counts"]["MEDIUM"] for entry in unique_images)
total_high += sum(entry["severity_counts"]["HIGH"] for entry in unique_images)
total_critical += sum(entry["severity_counts"]["CRITICAL"] for entry in unique_images)

# Add total counts to merged_data
merged_data["total"] = {
    "images": total_images,
    "LOW": total_low,
    "MEDIUM": total_medium,
    "HIGH": total_high,
    "CRITICAL": total_critical,
}

log("Summary in Json Format:")
log(json.dumps(merged_data, indent=4))


# Write the final output to a file
with open(summary_file, "w") as summary_file_handle:
    json.dump(merged_data, summary_file_handle, indent=4)

log(f"Summary written to: {summary_file} as JSON format")

# Load JSON content from the file
with open(summary_file, "r") as file_handle:
    data = json.load(file_handle)

# Define a mapping for working group names
working_group_name_mapping = {
    "Katib": "Katib",
    "Pipelines": "Pipelines",
    "Workspaces": "Workspaces(Notebooks)",
    "Kserve": "Kserve",
    "Manifests": "Manifests",
    "Trainer": "Trainer",
    "Model-registry": "Model Registry",
    "Spark": "Spark",
    "total": "All Images",
}

# Create PrettyTable
summary_table = PrettyTable()
summary_table.field_names = [
    "Working Group",
    "Images",
    "Critical CVE",
    "High CVE",
    "Medium CVE",
    "Low CVE",
]

# Populate the table with data
for working_group_key in working_group_name_mapping:
    if working_group_key in data:  # Check if the working group exists in the data
        working_group_data = data[working_group_key]
        summary_table.add_row(
            [
                working_group_name_mapping[working_group_key],
                working_group_data["images"],
                working_group_data["CRITICAL"],
                working_group_data["HIGH"],
                working_group_data["MEDIUM"],
                working_group_data["LOW"],
            ]
        )

# log the table
log(summary_table)

# Write the table output to a file in the specified folder
summary_table_output_file = (
    SUMMARY_OF_SEVERITY_COUNTS + "/summary_of_severity_counts_for_WGs_in_table.txt"
)
with open(summary_table_output_file, "w") as file_handle:
    file_handle.write(str(summary_table))

log("Output saved to:", summary_table_output_file)
log("Severity counts with images respect to WGs are saved in the", ALL_SEVERITY_COUNTS)
log("Scanned JSON reports on images are saved in", SCAN_REPORTS_DIR)
