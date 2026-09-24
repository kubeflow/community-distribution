#!/usr/bin/env python3
"""Fake helm and kubectl for tests/trainer_helm_lifecycle_control_flow_test.py.

Usage: trainer_helm_lifecycle_fake_cluster.py (helm|kubectl) ARGUMENT...

It imitates only what tests/trainer_helm_install.sh and
tests/trainer_helm_lifecycle_test.sh ask of a cluster with the three Trainer
releases. It proves control flow, never the behavior of a real cluster.

COMMAND_LOG receives every call as one line. FAKE_CLUSTER_STATE is the JSON file
that holds the objects, the releases, the manifests that kubectl create has
created and the TrainJobs that the imitated Trainer controller has reconciled.
FAIL_COMMAND fails every call whose line contains it; a final $ in it stands for
the end of the line.
FAKE_ADMIT_WITHOUT_RUNTIME=true admits a TrainJob whose runtime is absent,
FAKE_DENIAL_MESSAGE replaces the admission denial by another failure,
FAKE_SNAPSHOT_FOR_EXTERNAL_MANAGER=true reconciles a TrainJob that another
controller manages, and FAKE_UPGRADE_WITHOUT_EFFECT=true stores the revision of
an upgrade without changing a live object.

FAKE_UNREADABLE names objects as kind/name, separated by spaces. kubectl get and
kubectl wait of one of them fail as a denied read does, whether the object exists
or not; every other call treats it as usual. FAKE_APPEARING_OBJECT names one
snapshot or JobSet as kind/name. It comes into being, owned by its TrainJob, once
kubectl get has found it absent FAKE_APPEARS_AFTER_READS times (1 by default), so
the next read finds it.
"""

import json
import os
import re
import sys
from pathlib import Path

RELEASE_NAMESPACE = "kubeflow-system"
DEFINITIONS = (
    "clustertrainingruntimes.trainer.kubeflow.org",
    "trainingruntimes.trainer.kubeflow.org",
    "trainjobs.trainer.kubeflow.org",
    "jobsets.jobset.x-k8s.io",
)
TRAIN_JOB_DEFINITION = "trainjobs.trainer.kubeflow.org"
CONTROL_PLANE_OBJECTS = (
    ("deployment", RELEASE_NAMESPACE, "kubeflow-trainer-controller-manager"),
    ("deployment", RELEASE_NAMESPACE, "jobset-controller-manager"),
    ("endpoints", RELEASE_NAMESPACE, "kubeflow-trainer-controller-manager"),
    ("endpoints", RELEASE_NAMESPACE, "jobset-webhook-service"),
    ("mutatingwebhookconfiguration", "", "defaulter.trainer.kubeflow.org"),
    ("mutatingwebhookconfiguration", "", "jobset-mutating-webhook-configuration"),
    ("validatingwebhookconfiguration", "", "validator.trainer.kubeflow.org"),
    ("validatingwebhookconfiguration", "", "jobset-validating-webhook-configuration"),
)
KINDS = {
    "crd": "customresourcedefinition",
    "customresourcedefinition": "customresourcedefinition",
    "namespace": "namespace",
    "clustertrainingruntime": "clustertrainingruntime",
    "clustertrainingruntimes": "clustertrainingruntime",
    "trainingruntime": "trainingruntime",
    "trainjob": "trainjob",
    "jobset": "jobset",
    "configmap": "configmap",
    "deployment": "deployment",
    "endpoints": "endpoints",
    "mutatingwebhookconfiguration": "mutatingwebhookconfiguration",
    "validatingwebhookconfiguration": "validatingwebhookconfiguration",
}
NAMESPACED_KINDS = {
    "trainingruntime",
    "trainjob",
    "jobset",
    "configmap",
    "deployment",
    "endpoints",
}
OPTIONS_WITH_A_VALUE = {
    "--namespace",
    "-n",
    "-o",
    "--output",
    "-f",
    "--type",
    "-p",
    "--timeout",
    "--template",
}


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def load_yaml_documents(path):
    import yaml

    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    return [
        document
        for document in yaml.load_all(Path(path).read_text(), Loader=loader)
        if document
    ]


class Cluster:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists():
            self.state = json.loads(self.path.read_text())
        else:
            self.state = {
                "next_uid": 1,
                "objects": {},
                "releases": {},
                "created": {},
                "reconciled": [],
            }
            for name in (RELEASE_NAMESPACE, "kubeflow-user-example-com"):
                self.put("namespace", "", name, {})

    def save(self):
        self.path.write_text(json.dumps(self.state))

    @staticmethod
    def key(kind, namespace, name):
        return f"{kind}|{namespace if kind in NAMESPACED_KINDS else ''}|{name}"

    def get(self, kind, namespace, name):
        return self.state["objects"].get(self.key(kind, namespace, name))

    def put(self, kind, namespace, name, body):
        """Creates the object, or replaces its content and keeps its identity."""
        key = self.key(kind, namespace, name)
        existing = self.state["objects"].get(key)
        metadata = {"name": name} | body.get("metadata", {})
        if kind in NAMESPACED_KINDS:
            metadata["namespace"] = namespace
        if existing:
            content = {
                key: value for key, value in existing.items() if key != "metadata"
            }
            changed = content != {
                key: value for key, value in body.items() if key != "metadata"
            }
            metadata["uid"] = existing["metadata"]["uid"]
            metadata["generation"] = existing["metadata"]["generation"] + changed
        else:
            metadata["uid"] = f"uid-{self.state['next_uid']}"
            metadata["generation"] = 1
            self.state["next_uid"] += 1
        self.state["objects"][key] = body | {"metadata": metadata}
        return self.state["objects"][key]

    def delete(self, kind, namespace, name):
        removed = self.state["objects"].pop(self.key(kind, namespace, name), None)
        if removed:
            owner = removed["metadata"]["uid"]
            for key, candidate in list(self.state["objects"].items()):
                references = candidate["metadata"].get("ownerReferences", [])
                if any(reference["uid"] == owner for reference in references):
                    self.delete(*key.split("|"))
        return removed

    def release_is_deployed(self, name):
        return name in self.state["releases"]


def release_content(release, chart):
    """The objects of a release as [kind, namespace, name, body] entries."""
    chart = Path(chart)
    owner = {
        "annotations": {
            "meta.helm.sh/release-name": release,
            "meta.helm.sh/release-namespace": RELEASE_NAMESPACE,
        }
    }
    if release == "trainer-apis":
        definitions = chart / "charts/trainer-api-payload/manifests/definitions"
        content = []
        for name in DEFINITIONS:
            body = {"metadata": owner, "spec": {}}
            if name == TRAIN_JOB_DEFINITION and definitions.is_dir():
                # Only the property names of the specification are kept.
                (definition,) = load_yaml_documents(definitions / f"{name}.yaml")
                body["spec"]["versions"] = [
                    {
                        "name": version["name"],
                        "schema": {
                            "openAPIV3Schema": {
                                "properties": {
                                    "spec": {
                                        "properties": dict.fromkeys(
                                            version["schema"]["openAPIV3Schema"][
                                                "properties"
                                            ]["spec"]["properties"],
                                            {},
                                        )
                                    }
                                }
                            }
                        },
                    }
                    for version in definition["spec"]["versions"]
                ]
            content.append(["customresourcedefinition", "", name, body])
        return content
    if release == "trainer":
        annotations = {}
        for document in load_yaml_documents(
            chart / "manifests/platform-resources.yaml"
        ):
            if document["kind"] == "Deployment":
                annotations = document["spec"]["template"]["metadata"].get(
                    "annotations", {}
                )
        return [
            [
                kind,
                namespace,
                name,
                {
                    "metadata": owner,
                    "spec": {"template": {"metadata": {"annotations": annotations}}},
                },
            ]
            for kind, namespace, name in CONTROL_PLANE_OBJECTS
        ]
    if release == "trainer-runtimes":
        return [
            [
                "clustertrainingruntime",
                "",
                document["metadata"]["name"],
                {
                    "apiVersion": document["apiVersion"],
                    "kind": document["kind"],
                    "metadata": owner,
                    "spec": document["spec"],
                },
            ]
            for document in load_yaml_documents(
                chart / "manifests/platform-resources.yaml"
            )
        ]
    fail(f"unexpected release: {release}")


def apply_release(cluster, release, content, effective=True):
    history = cluster.state["releases"].setdefault(release, [])
    if not effective:
        content = history[-1]["content"]
    if history:
        kept = {(kind, namespace, name) for kind, namespace, name, _ in content}
        for kind, namespace, name, _ in history[-1]["content"]:
            if (kind, namespace, name) not in kept:
                cluster.delete(kind, namespace, name)
    for kind, namespace, name, body in content:
        cluster.put(kind, namespace, name, body)
    history.append({"revision": len(history) + 1, "content": content})


def helm(cluster, arguments):
    command = arguments[0]
    if command == "version":
        print("v4.2.2")
        return
    release = arguments[1]
    history = cluster.state["releases"].get(release)
    if command == "install":
        if history:
            fail(f"Error: INSTALLATION FAILED: cannot reuse a name: {release}")
        apply_release(cluster, release, release_content(release, arguments[2]))
        return
    if not history:
        fail(f"Error: release: not found: {release}")
    if command == "status":
        if "json" in arguments:
            print(
                json.dumps(
                    {"version": history[-1]["revision"], "info": {"status": "deployed"}}
                )
            )
    elif command == "history":
        print(json.dumps([{"revision": entry["revision"]} for entry in history]))
    elif command == "upgrade":
        effective = os.environ.get("FAKE_UPGRADE_WITHOUT_EFFECT") != "true"
        content = release_content(release, arguments[2])
        apply_release(cluster, release, content, effective)
    elif command == "rollback":
        (target,) = [
            entry for entry in history if entry["revision"] == int(arguments[2])
        ]
        apply_release(cluster, release, target["content"])
    elif command == "uninstall":
        for kind, namespace, name, _ in history[-1]["content"]:
            # The definitions carry helm.sh/resource-policy: keep.
            if kind != "customresourcedefinition":
                cluster.delete(kind, namespace, name)
        del cluster.state["releases"][release]
    else:
        fail(f"unexpected helm call: {' '.join(arguments)}")


def parse(arguments):
    positional, options = [], {}
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in OPTIONS_WITH_A_VALUE:
            options[argument] = arguments[index + 1]
            index += 1
        elif argument.startswith("-"):
            name, _, value = argument.partition("=")
            options[name] = value or True
        else:
            positional.append(argument)
        index += 1
    options["namespace"] = options.get("--namespace", options.get("-n", ""))
    options["output"] = options.get("-o", options.get("--output", ""))
    return positional, options


def resource(positional):
    if "/" in positional[0]:
        kind, name = positional[0].split("/", 1)
    else:
        kind, name = positional[0], (positional[1:] + [""])[0]
    if kind not in KINDS:
        fail(f"unexpected resource: {positional}")
    return KINDS[kind], name


def evaluate(expression, value):
    """A JSONPath of plain fields, escaped dots and list indexes."""
    fields = re.findall(r"\.((?:\\\.|[^.\[\]])+)|\[(\d+)\]", expression.strip("{}"))
    for field, index in fields:
        if isinstance(value, dict) and field:
            value = value.get(field.replace("\\.", "."))
        elif isinstance(value, list) and index and int(index) < len(value):
            value = value[int(index)]
        else:
            return ""
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True)


def runtime_of(cluster, job, namespace):
    reference = job["spec"]["runtimeRef"]
    kind = reference.get("kind", "ClusterTrainingRuntime").lower()
    return cluster.get(kind, namespace, reference["name"])


def admit(cluster, job, namespace):
    """The validating webhook exists only while the trainer release does."""
    if not cluster.release_is_deployed("trainer"):
        return
    if os.environ.get("FAKE_ADMIT_WITHOUT_RUNTIME") == "true":
        return
    if runtime_of(cluster, job, namespace):
        return
    name = job["spec"]["runtimeRef"]["name"]
    fail(
        os.environ.get("FAKE_DENIAL_MESSAGE")
        or 'Error from server (Forbidden): admission webhook "validator.trainjob.'
        'trainer.kubeflow.org" denied the request: spec.RuntimeRef: Invalid value: '
        f'clustertrainingruntimes.trainer.kubeflow.org "{name}" not found: specified '
        "clusterTrainingRuntime must be created before the TrainJob is created"
    )


def reconcile(cluster, job, namespace):
    """The Trainer controller: a runtime snapshot and a JobSet for its TrainJob."""
    import yaml

    external = "managedBy" in job["spec"]
    if external and os.environ.get("FAKE_SNAPSHOT_FOR_EXTERNAL_MANAGER") != "true":
        return
    runtime = runtime_of(cluster, job, namespace)
    if not cluster.release_is_deployed("trainer") or not runtime:
        return
    name = job["metadata"]["name"]
    cluster.state["reconciled"].append(cluster.key("trainjob", namespace, name))
    owner = {
        "ownerReferences": [
            {"kind": "TrainJob", "name": name, "uid": job["metadata"]["uid"]}
        ]
    }
    snapshot = {
        "apiVersion": "trainer.kubeflow.org/v1alpha1",
        "kind": job["spec"]["runtimeRef"].get("kind", "ClusterTrainingRuntime"),
        "metadata": {"name": runtime["metadata"]["name"]},
        "spec": runtime["spec"],
    }
    cluster.put(
        "configmap",
        namespace,
        f"{name}-runtime-snapshot",
        {"metadata": owner, "data": {"runtime": yaml.safe_dump(snapshot)}},
    )
    cluster.put(
        "jobset",
        namespace,
        name,
        {"metadata": owner, "spec": runtime["spec"]["template"]["spec"]},
    )


def appear(cluster, kind, namespace, name):
    """FAKE_APPEARING_OBJECT after enough reads that found it absent, else None."""
    if f"{kind}/{name}" != os.environ.get("FAKE_APPEARING_OBJECT"):
        return None
    reads = cluster.state.setdefault("absent_reads", {})
    key = cluster.key(kind, namespace, name)
    if reads.get(key, 0) < int(os.environ.get("FAKE_APPEARS_AFTER_READS", "1")):
        reads[key] = reads.get(key, 0) + 1
        return None
    job = cluster.get("trainjob", namespace, name.removesuffix("-runtime-snapshot"))
    owner = {"kind": "TrainJob"} | {
        key: job["metadata"][key] for key in ("name", "uid")
    }
    return cluster.put(
        kind, namespace, name, {"metadata": {"ownerReferences": [owner]}}
    )


def kubectl(cluster, arguments):
    command = arguments[0]
    positional, options = parse(arguments[1:])
    namespace = options["namespace"]
    if command == "create":
        (document,) = load_yaml_documents(options["-f"])
        kind, name = KINDS[document["kind"].lower()], document["metadata"]["name"]
        if cluster.get(kind, namespace, name):
            fail(f'Error from server (AlreadyExists): {kind} "{name}" already exists')
        if kind == "trainjob":
            admit(cluster, document, namespace)
        if options.get("--dry-run") == "server":
            return
        created = cluster.put(kind, namespace, name, document)
        cluster.state["created"][cluster.key(kind, namespace, name)] = document
        if kind == "trainjob":
            reconcile(cluster, created, namespace)
        return
    if command == "rollout":
        positional = positional[1:]
    kind, name = resource(positional)
    unreadable = os.environ.get("FAKE_UNREADABLE", "").split()
    if command in ("get", "wait") and f"{kind}/{name}" in unreadable:
        fail(
            f'Error from server (Forbidden): {kind} "{name}" is forbidden: '
            "the fake cluster denies this read"
        )
    found = cluster.get(kind, namespace, name) if name else None
    if command == "get":
        if not name:
            return
        found = found or appear(cluster, kind, namespace, name)
        if not found:
            if "--ignore-not-found" in options:
                return
            fail(f'Error from server (NotFound): {kind} "{name}" not found')
        output = options["output"]
        if output == "name":
            print(f"{kind}/{name}")
        elif output == "json":
            print(json.dumps(found))
        elif output.startswith("jsonpath="):
            print(evaluate(output.removeprefix("jsonpath="), found), end="")
    elif command == "patch":
        if not found:
            fail(f'Error from server (NotFound): {kind} "{name}" not found')
        admit(cluster, found, namespace)
        if options.get("--dry-run") != "server":
            found["spec"] |= json.loads(options["-p"])["spec"]
    elif command == "wait":
        condition = options["--for"]
        if (condition == "delete") == bool(found):
            fail("error: timed out waiting for the condition")
    elif command == "rollout":
        if not found:
            fail(f'Error from server (NotFound): {kind} "{name}" not found')
    elif command == "delete":
        if not cluster.delete(kind, namespace, name):
            if "--ignore-not-found" not in options:
                fail(f'Error from server (NotFound): {kind} "{name}" not found')
    else:
        fail(f"unexpected kubectl call: {' '.join(arguments)}")


def main():
    executable, arguments = sys.argv[1], sys.argv[2:]
    line = " ".join([executable, *arguments])
    with open(os.environ["COMMAND_LOG"], "a") as log:
        log.write(line + "\n")
    failure = os.environ.get("FAIL_COMMAND")
    if failure and failure in f"{line}$":
        fail(f"error: prepared failure of {line}")
    cluster = Cluster(os.environ["FAKE_CLUSTER_STATE"])
    {"helm": helm, "kubectl": kubectl}[executable](cluster, arguments)
    cluster.save()


if __name__ == "__main__":
    main()
