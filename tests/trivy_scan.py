# The script:
# 1. Extract all the images used by the Kubeflow Working Groups
# - The reported image lists are saved in respective files under ../image_lists directory
# 2. Scan the reported images using Trivy for security vulnerabilities
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

def get_trivy_binary():
    # Check both GitHub Actions and local installation directories
    for directory in ["/tmp/usr/local/bin", os.path.expandvars("$HOME/.local/bin")]:
        trivy_path = os.path.join(directory, "trivy")
        if os.path.isfile(trivy_path):
            return trivy_path
    return "trivy"

# Dictionary mapping Kubeflow workgroups to directories containing kustomization files
wg_dirs = {
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
    "workbenches": [
        # kubeflow/dashboard
        "../applications/dashboard/upstream/centraldashboard/overlays",
        "../applications/dashboard/upstream/poddefaults-webhooks/overlays",
        "../applications/dashboard/upstream/profile-controller/overlays",
        # kubeflow/notebooks
        "../applications/jupyter/jupyter-web-app/upstream/overlays",
        "../applications/jupyter/notebook-controller/upstream/overlays",
        "../applications/pvcviewer-controller/upstream/base",
        "../applications/tensorboard/tensorboard-controller/upstream/overlays",
        "../applications/tensorboard/tensorboards-web-app/upstream/overlays",
        "../applications/volumes-web-app/upstream/overlays",
    ],
    "kserve": [
        "../applications/kserve",
        "../applications/kserve/models-web-app/overlays/kubeflow",
    ],
    "model-registry": [
        "../applications/model-registry/upstream/options/istio",
        "../applications/model-registry/upstream/options/ui/overlays/istio",
        "../applications/model-registry/upstream/overlays/db",
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


def save_images(wg, images, version):
    # Saves a list of container images to a text file named after the workgroup and version.
    output_file = f"../image_lists/kf_{version}_{wg}_images.txt"
    with open(output_file, "w") as f:
        f.write("\n".join(images))
    log(f"File {output_file} successfully created")


def validate_semantic_version(version):
    # Validates a semantic version string (e.g., "0.1.2" or "latest").
    regex = r"^[0-9]+\.[0-9]+\.[0-9]+$"
    if re.match(regex, version) or version == "latest":
        return version
    else:
        raise ValueError(f"Invalid semantic version: '{version}'")


def extract_images(version):
    version = validate_semantic_version(version)
    log(f"Running the script using Kubeflow version: {version}")

    all_images = set()  # Collect all unique images across workgroups

    for wg, dirs in wg_dirs.items():
        wg_images = set()  # Collect unique images for this workgroup
        for dir_path in dirs:
            for root, _, files in os.walk(dir_path):
                for file in files:
                    if file in [
                        "kustomization.yaml",
                        "kustomization.yml",
                        "Kustomization",
                    ]:
                        full_path = os.path.join(root, file)
                        try:
                            # Execute `kustomize build` to render the kustomization file
                            result = subprocess.run(
                                ["kustomize", "build", root],
                                check=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                            )
                        except subprocess.CalledProcessError as e:
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
                        wg_images.update(kustomize_images)

        # Ensure uniqueness within workgroup images
        uniq_wg_images = sorted(wg_images)
        all_images.update(uniq_wg_images)
        save_images(wg, uniq_wg_images, version)

    # Ensure uniqueness across all workgroups
    uniq_images = sorted(all_images)
    save_images("all", uniq_images, version)


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

    with open(file, "r") as f:
        lines = f.readlines()

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
            result = subprocess.run(
                [
                    get_trivy_binary(),
                    "image",
                    "--format",
                    "json",
                    "--output",
                    scan_output_file,
                    line,
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            with open(scan_output_file, "r") as json_file:
                scan_data = json.load(json_file)

            if not scan_data.get("Results"):
                log(f"No vulnerabilities found in {image_name}:{image_tag}")
            else:
                vulnerabilities_list = [
                    result["Vulnerabilities"]
                    for result in scan_data["Results"]
                    if "Vulnerabilities" in result and result["Vulnerabilities"]
                ]

                if not vulnerabilities_list:
                    log(
                        f"The vulnerabilities detection may be insufficient because security updates are not provided for {image_name}:{image_tag}\n"
                    )
                else:
                    severity_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
                    for vulnerabilities in vulnerabilities_list:
                        for vulnerability in vulnerabilities:
                            severity = vulnerability.get("Severity", "UNKNOWN")
                            if severity == "UNKNOWN":
                                continue
                            elif severity in severity_counts:
                                severity_counts[severity] += 1

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

        except subprocess.CalledProcessError as e:
            log(f"Error scanning {image_name}:{image_tag}")
            log(e.stderr)

    # Combine all the JSON files into a single file with severity counts for all images
    json_files = glob.glob(os.path.join(severity_count, "*.json"))

    output_file = os.path.join(ALL_SEVERITY_COUNTS, f"{file_base_name}.json")

    if not json_files:
        log(f"No JSON files found in '{severity_count}'. Skipping combination.")
    else:
        combined_data = []
        for json_file in json_files:
            with open(json_file, "r") as jf:
                combined_data.append(json.load(jf))

        with open(output_file, "w") as of:
            json.dump({"data": combined_data}, of, indent=4)

        log(f"JSON files successfully combined into '{output_file}'")

# File to save summary of the severity counts for WGs as JSON format.
summary_file = os.path.join(
    SUMMARY_OF_SEVERITY_COUNTS, "severity_summary_in_json_format.json"
)

# Initialize counters
unique_images = {} # unique set of images across all WGs
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

    with open(file_path, "r") as f:
        data = json.load(f)["data"]

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
unique_images = unique_images.values() # keep the set of values
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
with open(summary_file, "w") as summary_f:
    json.dump(merged_data, summary_f, indent=4)

log(f"Summary written to: {summary_file} as JSON format")

# Load JSON content from the file
with open(summary_file, "r") as file:
    data = json.load(file)

# Define a mapping for working group names
working_group_name_mapping = {
    "Katib": "Katib",
    "Pipelines": "Pipelines",
    "Workbenches": "Workbenches(Notebooks)",
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
with open(summary_table_output_file, "w") as file:
    file.write(str(summary_table))

log("Output saved to:", summary_table_output_file)
log("Severity counts with images respect to WGs are saved in the", ALL_SEVERITY_COUNTS)
log("Scanned JSON reports on images are saved in", SCAN_REPORTS_DIR)
