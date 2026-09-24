#!/usr/bin/env python3

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_helm_kustomize_comparison as comparison  # noqa: E402
from comparison_partitions_test import package_chart_repository  # noqa: E402

ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
CHART_DIRECTORY = ROOT_DIRECTORY / "applications" / "spark" / "spark-operator" / "helm"
SYNCHRONIZATION_SCRIPT = (
    ROOT_DIRECTORY / "scripts" / "synchronize-spark-operator-manifests.sh"
)
INSTALLATION_SCRIPT = ROOT_DIRECTORY / "tests" / "spark_helm_install.sh"
LIBRARY = ROOT_DIRECTORY / "scripts" / "library.sh"
HELM_BINARY = os.environ.get("HELM_BINARY", "helm")
CHART_REPOSITORY = "https://kubeflow.github.io/spark-operator"

# The upstream chart derives resource names and spec.selector.matchLabels from
# .Release.Name, and the Kustomize baseline was rendered with this one.
RELEASE_NAME = "spark-operator"
OWNED_NAMESPACE = "kubeflow"
SIDECAR_INJECTION_LABEL = "sidecar.istio.io/inject"
AGGREGATED_ROLES = {
    "kubeflow-spark-admin",
    "kubeflow-spark-edit",
    "kubeflow-spark-view",
}
DIRECT_HELM_VARIABLES = (
    "HELM_REPOSITORY_CONFIG",
    "HELM_REPOSITORY_CACHE",
    "HELM_PLUGINS",
)
EMPTY_REPOSITORY_CONFIGURATION = (
    'apiVersion: ""\ngenerated: "0001-01-01T00:00:00Z"\nrepositories: []\n'
)

# Stands in for helm where a script needs a cluster or the network. It records
# the Helm environment of every invocation and, for `helm repo`, writes where
# Helm itself writes: the inherited direct paths when they are set, the home
# directories otherwise.
STAND_IN_HELM = """#!/usr/bin/env bash
{
  printf 'ARGUMENTS %s\\n' "$*"
  env | grep '^HELM_' || true
} >> "$STAND_IN_LOG"
case "$1" in
  version)
    echo v4.2.2
    ;;
  repo)
    configuration="${HELM_REPOSITORY_CONFIG:-${HELM_CONFIG_HOME:-$HOME/.config/helm}/repositories.yaml}"
    cache="${HELM_REPOSITORY_CACHE:-${HELM_CACHE_HOME:-$HOME/.cache/helm}/repository}"
    mkdir -p "$(dirname "$configuration")" "$cache"
    echo "changed by helm $*" >> "$configuration"
    touch "$cache/spark-operator-index.yaml"
    ;;
  template)
    echo "kind: StandIn"
    ;;
esac
"""
STAND_IN_NOTHING = "#!/usr/bin/env bash\nexit 0\n"


def snapshot(directory):
    """{relative path: content} of every entry under `directory`."""
    return {
        str(path.relative_to(directory)): path.read_bytes() if path.is_file() else None
        for path in sorted(Path(directory).rglob("*"))
    }


class HelmEnvironmentIsolationTest(unittest.TestCase):
    """The caller's Helm state survives the test, the installer and the
    synchronization script even when the caller exports the direct overrides.

    Nothing here needs the network or a cluster, so nothing here is skipped.
    """

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

        # What a developer may have exported: a repository configuration file,
        # a repository cache and a plugin directory outside the Helm homes.
        self.inherited = self.root / "inherited"
        (self.inherited / "cache").mkdir(parents=True)
        (self.inherited / "cache" / "existing-index.yaml").write_text("entries: {}\n")
        (self.inherited / "plugins").mkdir()
        (self.inherited / "repositories.yaml").write_text(
            EMPTY_REPOSITORY_CONFIGURATION
        )
        self.home = self.root / "home"
        self.home.mkdir()
        self.sentinels = {
            "HELM_REPOSITORY_CONFIG": str(self.inherited / "repositories.yaml"),
            "HELM_REPOSITORY_CACHE": str(self.inherited / "cache"),
            "HELM_PLUGINS": str(self.inherited / "plugins"),
            "HOME": str(self.home),
        }
        self.before = snapshot(self.inherited)

    def assertCallerStateUntouched(self):
        self.assertEqual(snapshot(self.inherited), self.before)
        self.assertEqual(snapshot(self.home), {})

    def serve_repository(self):
        url, server = package_chart_repository(
            self.root / "repository",
            {"example": [{"apiVersion": "v1", "kind": "Namespace"}]},
        )
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return url

    def test_helm_writes_to_the_inherited_paths_without_isolation(self):
        """The control: it proves that the sentinels below can detect a leak."""
        url = self.serve_repository()
        environment = dict(os.environ, **self.sentinels)
        for variable in ("HELM_CACHE_HOME", "HELM_CONFIG_HOME", "HELM_DATA_HOME"):
            environment[variable] = str(self.root / "helm" / variable.lower())

        subprocess.run(
            [HELM_BINARY, "repo", "add", "example", url],
            check=True,
            capture_output=True,
            env=environment,
        )

        self.assertNotEqual(snapshot(self.inherited), self.before)

    def test_the_test_environment_leaves_inherited_helm_paths_untouched(self):
        url = self.serve_repository()
        with mock.patch.dict(os.environ, self.sentinels):
            environment = comparison.helm_environment(self.root / "helm")

        for command in (
            [HELM_BINARY, "repo", "add", "example", url],
            [HELM_BINARY, "repo", "update"],
            [HELM_BINARY, "pull", "example/example", "--destination", str(self.root)],
        ):
            subprocess.run(command, check=True, capture_output=True, env=environment)

        self.assertCallerStateUntouched()
        self.assertTrue(
            (Path(environment["HELM_CONFIG_HOME"]) / "repositories.yaml").is_file()
        )

    def test_ordinary_comparison_preserves_caller_state_and_source_chart(self):
        url = self.serve_repository()
        chart = self.root / "chart"
        chart.mkdir()
        (chart / "Chart.yaml").write_text(
            "apiVersion: v2\nname: wrapper\nversion: 0.1.0\n"
            "dependencies:\n- name: example\n  version: 0.1.0\n"
            f"  repository: {url}\n"
        )
        descriptor = {
            "releaseName": "example",
            "namespace": "kubeflow",
            "dependencyRepositories": {"example": url},
            "scenarios": {"default": {"kustomize": []}},
        }
        chart_before = snapshot(chart)
        with (
            mock.patch.dict(os.environ, self.sentinels),
            mock.patch.object(comparison, "render_kustomize"),
            mock.patch.object(
                comparison.comparator, "compare_manifests", return_value=True
            ),
        ):
            self.assertTrue(
                comparison.compare(
                    "example", "default", {"example": (chart, descriptor)}, {}
                )
            )
        self.assertCallerStateUntouched()
        self.assertEqual(snapshot(chart), chart_before)

    def test_the_library_function_leaves_inherited_helm_paths_untouched(self):
        url = self.serve_repository()

        result = subprocess.run(
            [
                "bash",
                "-euc",
                'source "$1"; isolate_helm_environment "$2"; '
                '"$3" repo add example "$4"; "$3" repo update; '
                '"$3" pull example/example --destination "$2"; '
                'test -z "${HELM_REPOSITORY_CONFIG+set}${HELM_REPOSITORY_CACHE+set}'
                '${HELM_PLUGINS+set}"',
                "bash",
                str(LIBRARY),
                str(self.root / "helm"),
                HELM_BINARY,
                url,
            ],
            capture_output=True,
            text=True,
            env=dict(os.environ, **self.sentinels),
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertCallerStateUntouched()
        self.assertTrue(
            (self.root / "helm" / "configuration" / "repositories.yaml").is_file()
        )

    def stand_ins(self, *names):
        """A PATH whose first directory holds a stand-in helm and no-operation
        stand-ins for `names`; returns (environment, log path)."""
        directory = self.root / "stand-ins"
        directory.mkdir()
        for name, text in [("helm", STAND_IN_HELM)] + [
            (name, STAND_IN_NOTHING) for name in names
        ]:
            (directory / name).write_text(text)
            (directory / name).chmod(0o755)
        log = self.root / "helm-invocations.log"
        environment = dict(
            os.environ,
            **self.sentinels,
            PATH=f"{directory}{os.pathsep}{os.environ['PATH']}",
            STAND_IN_LOG=str(log),
        )
        return environment, log

    def assertEveryRepositoryInvocationIsolated(self, log):
        invocations = log.read_text().split("ARGUMENTS ")[1:]
        touching = [
            invocation
            for invocation in invocations
            if invocation.startswith(("repo ", "dependency "))
        ]
        self.assertTrue(
            any(invocation.startswith("repo add ") for invocation in touching),
            "the script never ran helm repo add",
        )
        for invocation in touching:
            with self.subTest(invocation=invocation.splitlines()[0]):
                variables = dict(
                    line.split("=", 1) for line in invocation.splitlines()[1:]
                )
                for variable in DIRECT_HELM_VARIABLES:
                    self.assertNotIn(variable, variables)
                for variable in (
                    "HELM_CACHE_HOME",
                    "HELM_CONFIG_HOME",
                    "HELM_DATA_HOME",
                ):
                    self.assertIn(variable, variables)
                    self.assertFalse(
                        Path(variables[variable]).is_relative_to(self.root), variable
                    )

    def test_the_installation_script_leaves_inherited_helm_paths_untouched(self):
        """The real script, with helm, kubectl and sleep replaced, so that it
        needs neither a cluster nor the network."""
        environment, log = self.stand_ins("kubectl", "sleep")

        result = subprocess.run(
            ["bash", str(INSTALLATION_SCRIPT)],
            capture_output=True,
            text=True,
            env=environment,
            cwd=ROOT_DIRECTORY,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEveryRepositoryInvocationIsolated(log)
        self.assertCallerStateUntouched()

    def test_the_synchronization_script_leaves_inherited_helm_paths_untouched(self):
        """The real script in a copy of the files it changes, with helm and git
        replaced, so that it needs no network and changes no source file."""
        tree = self.root / "tree"
        (tree / "scripts").mkdir(parents=True)
        for name in (LIBRARY.name, SYNCHRONIZATION_SCRIPT.name):
            shutil.copy(ROOT_DIRECTORY / "scripts" / name, tree / "scripts" / name)
        shutil.copy(ROOT_DIRECTORY / "README.md", tree / "README.md")
        shutil.copytree(
            CHART_DIRECTORY.parent,
            tree / CHART_DIRECTORY.parent.relative_to(ROOT_DIRECTORY),
            ignore=shutil.ignore_patterns("*.tgz"),
        )
        source = self.root / "source"
        (source / "spark-operator").mkdir(parents=True)
        environment, log = self.stand_ins("git")
        environment.update(
            KUBEFLOW_SYNCHRONIZE_NO_COMMIT="true", SOURCE_DIRECTORY=str(source)
        )

        result = subprocess.run(
            ["bash", str(tree / "scripts" / SYNCHRONIZATION_SCRIPT.name)],
            capture_output=True,
            text=True,
            env=environment,
            cwd=tree,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEveryRepositoryInvocationIsolated(log)
        self.assertCallerStateUntouched()


class SparkOperatorHelmChartTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Helm reads and writes repository configuration, the repository cache
        # and plugins under its three homes, unless HELM_REPOSITORY_CONFIG,
        # HELM_REPOSITORY_CACHE or HELM_PLUGINS point elsewhere. The comparison
        # harness isolates the homes and removes those three, which keeps the
        # developer's Helm state out of the test and the test out of it.
        cls.work_directory = tempfile.TemporaryDirectory()
        work_directory = Path(cls.work_directory.name)
        cls.environment = comparison.helm_environment(work_directory / "helm")

        # The dependency is built in a copy, so no archive is left in the
        # source tree.
        cls.chart_directory = work_directory / "chart"
        cls.source_tree_before = cls.source_tree()
        shutil.copytree(
            CHART_DIRECTORY, cls.chart_directory, ignore=shutil.ignore_patterns("*.tgz")
        )
        for command in (
            [HELM_BINARY, "repo", "add", "spark-operator", CHART_REPOSITORY],
            [HELM_BINARY, "dependency", "build", str(cls.chart_directory)],
        ):
            dependencies = subprocess.run(
                command, capture_output=True, text=True, env=cls.environment
            )
            if dependencies.returncode != 0:
                cls.work_directory.cleanup()
                message = f"chart dependency is unavailable: {dependencies.stderr}"
                # Continuous integration must never report a skipped suite as
                # a pass; a developer without network access may skip it.
                if os.environ.get("GITHUB_ACTIONS") == "true":
                    raise AssertionError(message)
                raise unittest.SkipTest(message)

        cls.manifests = cls.render()

    @staticmethod
    def source_tree():
        return sorted(
            str(path.relative_to(CHART_DIRECTORY))
            for path in CHART_DIRECTORY.rglob("*")
        )

    @classmethod
    def tearDownClass(cls):
        cls.work_directory.cleanup()

    @classmethod
    def template(cls, *values, release_name=RELEASE_NAME, namespace=OWNED_NAMESPACE):
        command = [
            HELM_BINARY,
            "template",
            release_name,
            str(cls.chart_directory),
            "--namespace",
            namespace,
            "--include-crds",
        ]
        for value in values:
            command.extend(["--set", value])
        return subprocess.run(
            command, capture_output=True, text=True, env=cls.environment
        )

    @classmethod
    def render(cls, *values):
        result = cls.template(*values)
        if result.returncode != 0:
            raise AssertionError(f"helm template failed: {result.stderr}")
        return [manifest for manifest in yaml.safe_load_all(result.stdout) if manifest]

    def find_manifest(self, manifests, kind, name):
        for manifest in manifests:
            if (
                manifest.get("kind") == kind
                and manifest.get("metadata", {}).get("name") == name
            ):
                return manifest
        raise AssertionError(f"{kind}/{name} was not rendered")

    def test_helm_homes_are_isolated_from_the_developer(self):
        for variable in ("HELM_CACHE_HOME", "HELM_CONFIG_HOME", "HELM_DATA_HOME"):
            with self.subTest(variable=variable):
                self.assertTrue(
                    self.environment[variable].startswith(self.work_directory.name)
                )
        for variable in DIRECT_HELM_VARIABLES:
            with self.subTest(variable=variable):
                self.assertNotIn(variable, self.environment)
        # Building the dependency left nothing behind in the source tree.
        self.assertEqual(self.source_tree(), self.source_tree_before)

    def test_chart_refuses_a_foreign_namespace(self):
        result = self.template(namespace="not-kubeflow")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be installed into the kubeflow namespace", result.stderr)

    def test_chart_refuses_a_foreign_release_name(self):
        """Upstream derives names and selector labels from the release name.

        helm lint exits 0 even when a fail guard fires, so only a render
        proves the guard.
        """
        result = self.template(release_name="spark")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "must be installed with the release name spark-operator", result.stderr
        )

    def test_external_operator_mode_renders_only_the_aggregated_roles(self):
        manifests = self.render("spark-operator.enabled=false")

        self.assertEqual(
            sorted(
                (manifest["kind"], manifest["metadata"]["name"])
                for manifest in manifests
            ),
            sorted(("ClusterRole", name) for name in AGGREGATED_ROLES),
        )

    def test_sidecar_injection_is_disabled_on_the_pod_template_only(self):
        """The Kustomize patches target spec.template.metadata.labels.

        Upstream places controller.labels and webhook.labels in the pod
        template. If a release ever moved them to the Deployment, the pods would
        silently rejoin the mesh while the rendered manifest still looked
        configured.
        """
        for name in ("spark-operator-controller", "spark-operator-webhook"):
            with self.subTest(deployment=name):
                deployment = self.find_manifest(self.manifests, "Deployment", name)

                pod_labels = deployment["spec"]["template"]["metadata"]["labels"]
                self.assertEqual(pod_labels.get(SIDECAR_INJECTION_LABEL), "false")

                deployment_labels = deployment["metadata"].get("labels", {})
                self.assertNotIn(SIDECAR_INJECTION_LABEL, deployment_labels)

    def test_job_namespaces_selects_every_namespace(self):
        """[""] renders --namespaces="", an empty list renders no argument.

        The synchronization script passes --set "spark.jobNamespaces={}", which
        Helm parses as a list holding the empty string, so the baseline carries
        the argument.
        """
        for name in ("spark-operator-controller", "spark-operator-webhook"):
            with self.subTest(deployment=name):
                deployment = self.find_manifest(self.manifests, "Deployment", name)
                arguments = deployment["spec"]["template"]["spec"]["containers"][0][
                    "args"
                ]
                self.assertIn('--namespaces=""', arguments)

    def test_aggregated_roles_can_be_disabled(self):
        rendered = {
            manifest["metadata"]["name"]
            for manifest in self.manifests
            if manifest.get("kind") == "ClusterRole"
        }
        self.assertTrue(AGGREGATED_ROLES.issubset(rendered))

        without_roles = self.render("kubeflow.aggregatedRoles.enabled=false")
        remaining = {
            manifest["metadata"]["name"]
            for manifest in without_roles
            if manifest.get("kind") == "ClusterRole"
        }

        self.assertEqual(remaining & AGGREGATED_ROLES, set())
        self.assertEqual(
            len(self.manifests) - len(without_roles), len(AGGREGATED_ROLES)
        )


class SparkOperatorSynchronizationTest(unittest.TestCase):
    """Checks that read files only, so they run without the chart repository."""

    def test_dependency_version_matches_the_synchronized_upstream_commit(self):
        """The one maintenance hazard a wrapper introduces, made into a test."""
        script = SYNCHRONIZATION_SCRIPT.read_text()
        commit = re.search(r'^COMMIT="v?([^"]+)"', script, re.MULTILINE)
        self.assertIsNotNone(commit, "COMMIT is not declared in the script")

        chart = yaml.safe_load((CHART_DIRECTORY / "Chart.yaml").read_text())
        dependency = next(
            entry
            for entry in chart["dependencies"]
            if entry["name"] == "spark-operator"
        )

        self.assertEqual(dependency["version"], commit.group(1))
        self.assertEqual(str(chart["appVersion"]), commit.group(1))

    def test_dependency_version_is_pinned_exactly(self):
        """A range would let two installations render differently."""
        chart = yaml.safe_load((CHART_DIRECTORY / "Chart.yaml").read_text())
        dependency = next(
            entry
            for entry in chart["dependencies"]
            if entry["name"] == "spark-operator"
        )

        self.assertRegex(dependency["version"], r"^\d+\.\d+\.\d+")

    def test_the_helm_version_guard_runs_before_anything_is_changed(self):
        lines = SYNCHRONIZATION_SCRIPT.read_text().splitlines()
        guard = lines.index('require_helm_version "$HELM_VERSION"')
        for mutation in ("create_branch ", "clone_and_checkout ", "helm template "):
            first = next(
                index for index, line in enumerate(lines) if line.startswith(mutation)
            )
            self.assertLess(guard, first, mutation)

    def run_library(self, command, helm_version):
        """Run a scripts/library.sh function against a stand-in helm."""
        with tempfile.TemporaryDirectory() as directory:
            helm = Path(directory) / "helm"
            helm.write_text(f"#!/usr/bin/env bash\necho '{helm_version}'\n")
            helm.chmod(0o755)
            environment = dict(
                os.environ, PATH=f"{directory}{os.pathsep}{os.environ['PATH']}"
            )
            return subprocess.run(
                [
                    "bash",
                    "-c",
                    f'source "{ROOT_DIRECTORY}/scripts/library.sh"; {command}',
                ],
                capture_output=True,
                text=True,
                env=environment,
            )

    def test_the_helm_version_guard_is_exact_and_accepts_build_metadata(self):
        for found, accepted in (
            ("v4.2.2", True),
            ("v4.2.2+g1a2b3c4", True),
            ("v4.2.3", False),
            ("v4.3.0", False),
            ("v4.2.20", False),
            ("v3.18.4", False),
        ):
            with self.subTest(found=found):
                result = self.run_library("require_helm_version v4.2.2", found)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                if not accepted:
                    self.assertIn("Helm v4.2.2 required", result.stderr)

    def test_one_version_bump_changes_every_version_string(self):
        """Run the script's own update function against a copy of the chart."""
        script = SYNCHRONIZATION_SCRIPT.read_text()
        function = re.search(
            r"^update_spark_operator_helm_chart\(\) \{\n.*?^\}\n",
            script,
            re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(function)
        current = re.search(r'^COMMIT="v([^"]+)"', script, re.MULTILINE).group(1)

        with tempfile.TemporaryDirectory() as directory:
            chart = Path(directory) / "chart"
            shutil.copytree(CHART_DIRECTORY, chart)
            before = yaml.safe_load((chart / "Chart.yaml").read_text())
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    f'source "{ROOT_DIRECTORY}/scripts/library.sh"\n'
                    f"{function.group(0)}\n"
                    "update_spark_operator_helm_chart",
                ],
                capture_output=True,
                text=True,
                env=dict(os.environ, COMMIT="v97.98.99", CHART_DIRECTORY=str(chart)),
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            after = yaml.safe_load((chart / "Chart.yaml").read_text())
            readme = (chart / "README.md").read_text()
            chart_text = (chart / "Chart.yaml").read_text()

        self.assertEqual(after["appVersion"], "97.98.99")
        self.assertEqual(after["dependencies"][0]["version"], "97.98.99")
        # The anchored expression leaves the chart's own version alone.
        self.assertEqual(after["version"], before["version"])
        self.assertNotIn(current, chart_text)
        self.assertNotIn(current, readme)
        self.assertIn("upstream Spark Operator `v97.98.99`", readme)
        self.assertIn("--version 97.98.99", readme)

    def test_chart_carries_no_crds_directory(self):
        """The dependency owns the definitions; a second copy would collide.

        Resources installed from a subchart crds directory carry no Helm
        ownership metadata, so declaring the same ones here would fail the
        ownership check on install.
        """
        self.assertFalse((CHART_DIRECTORY / "crds").exists())


def main():
    """Run the suite and state the outcome so that a skip cannot read as a pass.

    unittest prints "OK (skipped=1)" and exits 0 when setUpClass skips, although
    that one entry stands for every test of the class. The summary counts the
    tests, and a run with skipped tests exits 2: not failed, and not passed.
    """
    program = unittest.main(exit=False)
    result = program.result
    class_size = len(unittest.TestLoader().getTestCaseNames(SparkOperatorHelmChartTest))
    skipped = sum(
        1 if isinstance(test, unittest.TestCase) else class_size
        for test, _ in result.skipped
    )
    print(
        f"Spark Operator Helm chart tests: {result.testsRun} ran, "
        f"{skipped} skipped, {len(result.failures)} failed, "
        f"{len(result.errors)} errors.",
        file=sys.stderr,
    )
    if not result.wasSuccessful():
        sys.exit(1)
    if skipped:
        print(
            f"INCOMPLETE: {skipped} tests were skipped, so this run is not a pass.",
            file=sys.stderr,
        )
        sys.exit(2)


if __name__ == "__main__":
    main()
