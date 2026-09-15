#!/usr/bin/env python3
"""A partition group's releases must own their shared baseline exactly once.

A component whose resources form several releases ships sibling charts that
declare `partition: <group>` and select their share of one Kustomize baseline
with onlyKinds and excludeKinds. Selection alone proves nothing about what a
release creates: the ordinary comparison filters both sides, so three charts
that each render the whole component would pass three green subset
comparisons. The check verified here reads each member's complete rendered
output and requires it to be exactly the member's owned subset, with the
union of the subsets equal to the baseline.

Every fixture is a real chart tree rendered with helm and kustomize in a
temporary repository root, through the same callable the --partitions
command uses.
"""

import copy
import functools
import http.server
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_helm_kustomize_comparison as comparison  # noqa: E402

BASELINE_PATH = "applications/example/base"
CRD = {
    "apiVersion": "apiextensions.k8s.io/v1",
    "kind": "CustomResourceDefinition",
    "metadata": {"name": "widgets.example.org"},
    "spec": {
        "group": "example.org",
        "names": {"kind": "Widget", "plural": "widgets"},
        "scope": "Cluster",
        "versions": [
            {
                "name": "v1",
                "served": True,
                "storage": True,
                "schema": {"openAPIV3Schema": {"type": "object"}},
            }
        ],
    },
}
CONTROLLER = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {"name": "example-controller", "namespace": "kubeflow"},
    "spec": {"selector": {"matchLabels": {"app": "example"}}, "template": {}},
}
CONFIGURATION = {
    "apiVersion": "v1",
    "kind": "ConfigMap",
    "metadata": {"name": "example-config", "namespace": "kubeflow"},
    "data": {"level": "info"},
}
# Kustomize attaches metadata.namespace to this cluster-scoped object, as the
# real Trainer overlay does for ClusterTrainingRuntime.
RUNTIME = {
    "apiVersion": "example.org/v1",
    "kind": "Widget",
    "metadata": {"name": "default", "namespace": "kubeflow"},
}
BASELINE = [CRD, CONTROLLER, CONFIGURATION, RUNTIME]

MEMBERS = {
    # directory name: (descriptor scenario selection, owned baseline objects)
    "helm-crds": ({"onlyKinds": ["CustomResourceDefinition"]}, [CRD]),
    "helm": (
        {"excludeKinds": ["CustomResourceDefinition", "Widget"]},
        [CONTROLLER, CONFIGURATION],
    ),
    "helm-runtimes": ({"onlyKinds": ["Widget"]}, [RUNTIME]),
}


def dump(objects):
    return yaml.safe_dump_all(objects, sort_keys=False)


def write_baseline(root, objects=BASELINE):
    base = root / BASELINE_PATH
    base.mkdir(parents=True, exist_ok=True)
    (base / "resources.yaml").write_text(dump(objects))
    (base / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1beta1\nkind: Kustomization\n"
        "resources:\n- resources.yaml\n"
    )


def write_member(
    root,
    directory,
    selection,
    objects,
    group="example",
    scenario="platform",
    kustomize=(BASELINE_PATH,),
    thin_parent=False,
    declared_dependency=False,
    dependency_crds_directory=False,
    dependency_repository=None,
):
    """A chart under applications/example/<directory> rendering `objects`.

    With `dependency_repository`, the objects come from a chart named
    payload-<directory> that the member declares from that Helm repository URL
    through `dependencyRepositories`; nothing is vendored under charts/.
    """
    chart = root / "applications/example" / directory
    # A rewritten member starts from an empty chart tree.
    shutil.rmtree(chart, ignore_errors=True)
    if dependency_repository:
        (chart / "templates").mkdir(parents=True)
        (chart / "Chart.yaml").write_text(
            f"apiVersion: v2\nname: {directory}\nversion: 0.1.0\n"
            f"dependencies:\n- name: payload-{directory}\n  version: 0.1.0\n"
            f"  repository: {dependency_repository}\n"
        )
        (chart / "ci").mkdir()
        descriptor = {
            "component": f"example-{directory}",
            "releaseName": f"example-{directory}",
            "namespace": "kubeflow",
            "partition": group,
            "dependencyRepositories": {"shared": dependency_repository},
            "scenarios": {scenario: {"kustomize": list(kustomize), **selection}},
        }
        (chart / "ci" / "comparison.yaml").write_text(yaml.safe_dump(descriptor))
        return chart
    payload_chart = chart / "charts" / "payload" if thin_parent else chart
    (payload_chart / "templates").mkdir(parents=True, exist_ok=True)
    (payload_chart / "manifests").mkdir(exist_ok=True)
    (payload_chart / "manifests" / "objects.yaml").write_text(dump(objects))
    (payload_chart / "templates" / "objects.yaml").write_text(
        '{{ .Files.Get "manifests/objects.yaml" }}\n'
    )
    if thin_parent:
        (payload_chart / "Chart.yaml").write_text(
            "apiVersion: v2\nname: payload\nversion: 0.1.0\n"
        )
        (chart / "templates").mkdir(exist_ok=True)
        if dependency_crds_directory:
            # Install-once content inside the dependency instead of a template.
            (payload_chart / "templates" / "objects.yaml").unlink()
            (payload_chart / "crds").mkdir()
            (payload_chart / "crds" / "objects.yaml").write_text(dump(objects))
    chart_yaml = f"apiVersion: v2\nname: {directory}\nversion: 0.1.0\n"
    if declared_dependency:
        chart_yaml += (
            "dependencies:\n- name: payload\n  version: 0.1.0\n"
            "  repository: file://charts/payload\n"
        )
    (chart / "Chart.yaml").write_text(chart_yaml)
    (chart / "ci").mkdir(exist_ok=True)
    descriptor = {
        "component": f"example-{directory}",
        "releaseName": f"example-{directory}",
        "namespace": "kubeflow",
        "partition": group,
        "scenarios": {scenario: {"kustomize": list(kustomize), **selection}},
    }
    (chart / "ci" / "comparison.yaml").write_text(yaml.safe_dump(descriptor))
    return chart


def write_group(root, rendered=None, **member_overrides):
    """The valid three-chart group, unless a member's objects are overridden."""
    write_baseline(root)
    charts = {}
    for directory, (selection, owned) in MEMBERS.items():
        objects = (rendered or {}).get(directory, owned)
        charts[directory] = write_member(
            root, directory, selection, objects, **member_overrides
        )
    return charts


class QuietRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *arguments):
        """Request lines are noise in a test report."""


def package_chart_repository(directory, charts):
    """Package `charts` ({name: objects}) into a served Helm repository.

    Returns (url, server); stop the server with server.shutdown().
    """
    directory.mkdir(parents=True)
    for name, objects in charts.items():
        source = directory / "source" / name
        (source / "templates").mkdir(parents=True)
        (source / "manifests").mkdir()
        (source / "Chart.yaml").write_text(
            f"apiVersion: v2\nname: {name}\nversion: 0.1.0\n"
        )
        (source / "manifests" / "objects.yaml").write_text(dump(objects))
        (source / "templates" / "objects.yaml").write_text(
            '{{ .Files.Get "manifests/objects.yaml" }}\n'
        )
        subprocess.run(
            ["helm", "package", str(source), "--destination", str(directory)],
            check=True,
            capture_output=True,
        )
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0),
        functools.partial(QuietRequestHandler, directory=str(directory)),
    )
    url = f"http://127.0.0.1:{server.server_address[1]}"
    subprocess.run(
        ["helm", "repo", "index", str(directory), "--url", url],
        check=True,
        capture_output=True,
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return url, server


class PartitionGroupTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def verify(self):
        descriptors = comparison.discover(self.root)
        return comparison.verify_partitions(descriptors, self.root)

    def assertProblem(self, problems, *fragments):
        for fragment in fragments:
            self.assertTrue(
                any(fragment in line for line in problems),
                f"{fragment!r} not reported in:\n" + "\n".join(problems),
            )

    def test_disjoint_releases_covering_the_baseline_pass(self):
        write_group(self.root)

        self.assertEqual(self.verify(), [])

    def test_every_release_rendering_the_whole_baseline_fails(self):
        """The counterexample the ordinary comparison cannot see: selectors
        differ and partition the source, yet each release creates everything."""
        write_group(self.root, rendered={name: BASELINE for name in MEMBERS})

        problems = self.verify()

        self.assertProblem(
            problems,
            "example/platform example-helm-crds: renders Deployment.apps/kubeflow/"
            "example-controller, which its selection does not own",
            "example/platform example-helm: renders Widget.example.org/default, "
            "which its selection does not own",
            "example/platform example-helm-runtimes: renders "
            "CustomResourceDefinition.apiextensions.k8s.io/widgets.example.org, "
            "which its selection does not own",
        )

    def test_a_release_missing_an_owned_object_fails(self):
        write_group(self.root, rendered={"helm": [CONTROLLER]})

        self.assertProblem(
            self.verify(),
            "example/platform example-helm: does not render "
            "ConfigMap/kubeflow/example-config, which its selection owns",
        )

    def test_a_release_rendering_an_object_outside_the_baseline_fails(self):
        stray = copy.deepcopy(CONFIGURATION)
        stray["metadata"]["name"] = "example-extra"
        write_group(self.root, rendered={"helm": [CONTROLLER, CONFIGURATION, stray]})

        self.assertProblem(
            self.verify(),
            "example/platform example-helm: renders ConfigMap/kubeflow/example-extra, "
            "which is not in the baseline",
        )

    def test_a_duplicate_identity_in_a_release_fails_before_deduplication(self):
        write_group(self.root, rendered={"helm-runtimes": [RUNTIME, RUNTIME]})

        self.assertProblem(
            self.verify(),
            "example/platform example-helm-runtimes renders Widget.example.org/default twice",
        )

    def test_a_duplicate_identity_in_the_baseline_fails(self):
        """Kustomize itself refuses to build a duplicate identity; the inventory
        refuses one too, for a baseline assembled from several targets."""
        write_group(self.root)
        write_baseline(self.root, BASELINE + [CONTROLLER])
        self.assertProblem(self.verify(), "example/platform: kustomize build")

        _, problems = comparison.inventory(
            BASELINE + [CONTROLLER], comparison.cluster_scoped_kinds(BASELINE), "b"
        )
        self.assertEqual(
            problems, ["b renders Deployment.apps/kubeflow/example-controller twice"]
        )

    def test_an_object_owned_by_two_selections_fails(self):
        write_group(self.root)
        write_member(
            self.root,
            "helm-runtimes",
            {"onlyKinds": ["Widget", "ConfigMap"]},
            [RUNTIME, CONFIGURATION],
        )

        self.assertProblem(
            self.verify(),
            "example/platform: ConfigMap/kubeflow/example-config is owned by "
            "example-helm, example-helm-runtimes",
        )

    def test_an_object_owned_by_no_selection_fails(self):
        write_group(self.root)
        write_member(
            self.root,
            "helm",
            {"excludeKinds": ["CustomResourceDefinition", "Widget", "ConfigMap"]},
            [CONTROLLER],
        )

        self.assertProblem(
            self.verify(),
            "example/platform: ConfigMap/kubeflow/example-config is owned by no member",
        )

    def test_members_with_different_scenarios_or_baselines_fail(self):
        write_group(self.root)
        selection, owned = MEMBERS["helm-runtimes"]
        write_member(self.root, "helm-runtimes", selection, owned, scenario="other")
        self.assertProblem(
            self.verify(), "example: members declare different scenarios"
        )

        write_member(
            self.root,
            "helm-runtimes",
            selection,
            owned,
            kustomize=(BASELINE_PATH, "applications/example/other"),
        )
        self.assertProblem(
            self.verify(),
            "example/platform: members compare against different Kustomize targets",
        )

    def test_a_group_of_one_chart_fails(self):
        write_baseline(self.root)
        write_member(self.root, "helm", {}, BASELINE)

        self.assertEqual(
            self.verify(), ["example: a partition group needs at least two charts"]
        )

    def test_install_once_crds_content_is_rejected(self):
        charts = write_group(self.root, rendered={"helm-crds": []})
        (charts["helm-crds"] / "crds").mkdir()
        (charts["helm-crds"] / "crds" / "widgets.yaml").write_text(dump([CRD]))

        self.assertProblem(
            self.verify(),
            "example example-helm-crds: install-once crds/ content is not "
            "supported in a partition group; render definitions from templates: "
            "widgets.example.org",
        )

    def test_install_once_crds_content_inside_a_dependency_is_rejected(self):
        """--include-crds renders a dependency's crds/ too, so the release would
        pass ownership while the definitions had the install-once lifecycle."""
        selection, owned = MEMBERS["helm-crds"]
        for declared in (False, True):
            with self.subTest(declared_dependency=declared):
                write_group(self.root)
                write_member(
                    self.root,
                    "helm-crds",
                    selection,
                    owned,
                    thin_parent=True,
                    declared_dependency=declared,
                    dependency_crds_directory=True,
                )

                self.assertProblem(
                    self.verify(),
                    "example example-helm-crds: install-once crds/ content is not "
                    "supported in a partition group; render definitions from "
                    "templates: widgets.example.org",
                )

    def test_a_declared_local_dependency_is_built_in_the_copy_and_passes(self):
        """The Trainer definitions packaging: a parent that declares its payload
        chart as a file:// dependency and renders every definition from templates."""
        write_group(self.root)
        selection, owned = MEMBERS["helm-crds"]
        chart = write_member(
            self.root,
            "helm-crds",
            selection,
            owned,
            thin_parent=True,
            declared_dependency=True,
        )
        before = sorted(str(path) for path in chart.rglob("*"))

        self.assertEqual(self.verify(), [])
        self.assertEqual(sorted(str(path) for path in chart.rglob("*")), before)

    def test_members_sharing_a_dependency_repository_are_all_prepared(self):
        """Two members declare the same repository name and URL; adding it a
        second time into the group's shared Helm home must not abort the run."""
        repository = self.root / "repository"
        url, server = package_chart_repository(
            repository,
            {
                "payload-helm-crds": MEMBERS["helm-crds"][1],
                "payload-helm-runtimes": MEMBERS["helm-runtimes"][1],
            },
        )
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        write_group(self.root)
        for directory in ("helm-crds", "helm-runtimes"):
            selection, owned = MEMBERS[directory]
            write_member(
                self.root, directory, selection, owned, dependency_repository=url
            )

        self.assertEqual(self.verify(), [])
        self.assertEqual(
            sorted(path.name for path in repository.iterdir()),
            [
                "index.yaml",
                "payload-helm-crds-0.1.0.tgz",
                "payload-helm-runtimes-0.1.0.tgz",
                "source",
            ],
        )

    def test_every_scenario_of_a_group_is_verified(self):
        """Two valid scenarios pass; a defect present only in the second one
        is reported for that scenario alone."""
        write_group(self.root)
        for chart in (self.root / "applications/example").glob("helm*"):
            path = chart / "ci/comparison.yaml"
            descriptor = yaml.safe_load(path.read_text())
            descriptor["scenarios"]["standalone"] = copy.deepcopy(
                descriptor["scenarios"]["platform"]
            )
            descriptor["defaultScenario"] = "platform"
            path.write_text(yaml.safe_dump(descriptor))
        self.assertEqual(self.verify(), [])

        path = self.root / "applications/example/helm-runtimes/ci/comparison.yaml"
        descriptor = yaml.safe_load(path.read_text())
        descriptor["scenarios"]["standalone"]["onlyKinds"] = ["Widget", "ConfigMap"]
        path.write_text(yaml.safe_dump(descriptor))

        problems = self.verify()

        self.assertProblem(
            problems,
            "example/standalone example-helm-runtimes: does not render "
            "ConfigMap/kubeflow/example-config, which its selection owns",
            "example/standalone: ConfigMap/kubeflow/example-config is owned by "
            "example-helm, example-helm-runtimes",
        )
        self.assertFalse(any("example/platform" in line for line in problems), problems)

    def test_a_hook_object_is_rejected(self):
        hooked = copy.deepcopy(RUNTIME)
        hooked["metadata"]["annotations"] = {"helm.sh/hook": "post-install"}
        write_group(self.root, rendered={"helm-runtimes": [hooked]})

        self.assertProblem(
            self.verify(),
            "example/platform example-helm-runtimes: Widget.example.org/default is a "
            "Helm hook",
        )

    def test_a_thin_parent_release_is_inventoried_through_its_dependency(self):
        """The intended packaging of a large definitions release: an empty
        parent whose objects come from a chart under charts/."""
        write_group(self.root)
        selection, owned = MEMBERS["helm-crds"]
        write_member(self.root, "helm-crds", selection, owned, thin_parent=True)

        self.assertEqual(self.verify(), [])
        self.assertEqual(
            [chart.name for chart in comparison.chart_directories(self.root)],
            ["helm", "helm-crds", "helm-runtimes"],
        )

    def test_a_namespace_on_a_cluster_scoped_custom_resource_is_not_identity(self):
        """The release renders the runtime without the namespace Kustomize
        attaches; the baseline's own definition says the kind is cluster-scoped,
        so both are one object."""
        unnamespaced = copy.deepcopy(RUNTIME)
        del unnamespaced["metadata"]["namespace"]
        write_group(self.root, rendered={"helm-runtimes": [unnamespaced]})

        self.assertEqual(self.verify(), [])

    def test_a_repository_without_groups_has_nothing_to_verify(self):
        write_baseline(self.root)
        chart = write_member(self.root, "helm", {}, BASELINE)
        descriptor = yaml.safe_load((chart / "ci/comparison.yaml").read_text())
        del descriptor["partition"]
        (chart / "ci/comparison.yaml").write_text(yaml.safe_dump(descriptor))

        descriptors = comparison.discover(self.root)

        self.assertEqual(comparison.partition_groups(descriptors), {})
        self.assertEqual(comparison.verify_partitions(descriptors, self.root), [])

    def test_the_checkout_is_not_modified_by_rendering(self):
        charts = write_group(self.root)
        before = sorted(str(path) for path in self.root.rglob("*"))

        self.verify()

        self.assertEqual(sorted(str(path) for path in self.root.rglob("*")), before)
        self.assertFalse((charts["helm"] / "Chart.lock").exists())


class RepositoryPartitionsTest(unittest.TestCase):
    """The live command works before and after the first group is declared."""

    def test_the_partitions_command_verifies_every_declared_group(self):
        result = subprocess.run(
            [sys.executable, "tests/run_helm_kustomize_comparison.py", "--partitions"],
            cwd=comparison.ROOT_DIRECTORY,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        groups = comparison.partition_groups(comparison.discover())
        if groups:
            self.assertIn("SUCCESS:", result.stdout)
            for group in groups:
                self.assertIn(group, result.stdout)
        else:
            self.assertIn("No partition groups declared", result.stdout)


if __name__ == "__main__":
    unittest.main()
