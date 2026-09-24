#!/usr/bin/env python3
"""Cluster-free control flow of tests/trainer_helm_lifecycle_test.sh.

The lifecycle script and the installer run unchanged in a miniature repository,
against tests/trainer_helm_lifecycle_fake_cluster.py as helm and kubectl. Only
tests/trainer_test.sh is replaced, because it needs the Kubeflow SDK. This proves
the selection of scenarios, the order of the calls, that a reinstallation issues
the calls of the installer, that no call carries a force option, that only
objects of the same run are deleted and that a failed read never counts as the
absence of an object. It proves nothing about a real cluster.

Every run is independent of the others, so all of them start together in
setUpClass and a test waits only for the runs that it inspects.
"""

import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKE_CLUSTER = ROOT / "tests/trainer_helm_lifecycle_fake_cluster.py"
LIFECYCLE_TEST = "tests/trainer_helm_lifecycle_test.sh"
INSTALLER = "tests/trainer_helm_install.sh"
RELEASES = ["trainer-apis", "trainer", "trainer-runtimes"]
SCENARIOS = [
    "smoke",
    "fixtures",
    "controller-upgrade-rollback",
    "controller-reinstall",
    "api-upgrade",
    "api-reinstall",
    "catalog-update-rollback",
    "retirement-after-snapshot",
    "retirement-before-snapshot",
]
STATUS_CALLS = [
    f"helm status {release} --namespace kubeflow-system --output json"
    for release in RELEASES
]
NAMESPACE = "kubeflow-user-example-com"
PREFIX = "trainer-lifecycle-control-flow"
FIXTURES = [
    f"clustertrainingruntime||{PREFIX}-administrator",
    f"trainingruntime|{NAMESPACE}|{PREFIX}-namespaced",
    f"trainjob|{NAMESPACE}|{PREFIX}-catalog-job",
    f"trainjob|{NAMESPACE}|{PREFIX}-namespaced-job",
]
FOREIGN_OBJECTS = [
    "clustertrainingruntime||team-runtime",
    f"trainjob|{NAMESPACE}|team-job",
]
FORCE_OPTIONS = ("--force", "--take-ownership")
CONNECTION_FAILURE = (
    "Error from server (InternalError): Internal error occurred: failed calling "
    'webhook "validator.trainjob.trainer.kubeflow.org": connection refused'
)
PACKAGED_CHART = "{packaged chart}"
HELD_JOB = f"{PREFIX}-unmanaged-job"
HELD_SNAPSHOT = f"configmap/{HELD_JOB}-runtime-snapshot"
HELD_JOB_SET = f"jobset/{HELD_JOB}"
ABSENCE_READ = "kubectl get {} --namespace " + NAMESPACE + " --ignore-not-found -o name"
KUEUE_DEFINITION = "customresourcedefinition/workloads.kueue.x-k8s.io"
NOT_READ = "could not be read, which is no evidence that it is absent"
# The held TrainJob is read twice in the window of one second, once while the
# runtime is absent and once at the end, so the number of reads that still find
# the object absent selects the check that must find it.
APPEARING = {
    "snapshot in the window": (HELD_SNAPSHOT, 1, "within 1 seconds of its creation"),
    "JobSet in the window": (HELD_JOB_SET, 1, "within 1 seconds of its creation"),
    "snapshot during the retirement": (
        HELD_SNAPSHOT,
        2,
        "while torch-distributed is absent",
    ),
    "JobSet at the end": (HELD_JOB_SET, 3, "at the end of the scenario"),
}
# Each fragment is the read of one check whose good news is an absent object.
UNREAD_ABSENCE_CHECKS = {
    "fixtures": f"clustertrainingruntime/{PREFIX}-administrator --ignore-not-found",
    "controller-reinstall": "jobset-validating-webhook-configuration --ignore-not-found",
    "retirement-after-snapshot": "clustertrainingruntime/torch-distributed --ignore-not-found",
}
WITHOUT_EFFECT = {
    "controller-upgrade-rollback": "does not carry the changed Pod template",
    "api-upgrade": "does not serve the property",
    "catalog-update-rollback": "after the catalog update",
}


def lifecycle(*arguments, existing=(), **variables):
    """One run of the lifecycle test: arguments, foreign objects and variables."""
    return arguments, list(existing), variables


def fixture_name(position):
    return FIXTURES[position].split("|")[2]


RUNS = {
    "not disposable": lifecycle(NAMESPACE, "all", TRAINER_HELM_LIFECYCLE_DISPOSABLE=""),
    "no kubeconfig": lifecycle(NAMESPACE, "all", KUBECONFIG=""),
    "unknown scenario": lifecycle(NAMESPACE, "catalog-update"),
    "long identifier": lifecycle(
        NAMESPACE, "fixtures", TRAINER_HELM_LIFECYCLE_RUN_IDENTIFIER="a" * 16
    ),
    "default identifier": lifecycle(
        NAMESPACE, "fixtures", TRAINER_HELM_LIFECYCLE_RUN_IDENTIFIER=""
    ),
    "all with another scenario": lifecycle(NAMESPACE, "all", "smoke"),
    "no argument": lifecycle(),
    "namespace only": lifecycle(NAMESPACE),
    "variable": lifecycle(NAMESPACE, TRAINER_HELM_LIFECYCLE_SCENARIOS="smoke fixtures"),
    "argument over variable": lifecycle(
        NAMESPACE, "smoke", TRAINER_HELM_LIFECYCLE_SCENARIOS="smoke fixtures"
    ),
    "complete": lifecycle(NAMESPACE, "all", existing=FOREIGN_OBJECTS),
    "snapshot for an external manager": lifecycle(
        NAMESPACE,
        "retirement-before-snapshot",
        FAKE_SNAPSHOT_FOR_EXTERNAL_MANAGER="true",
    ),
    "kueue": lifecycle(
        NAMESPACE,
        "retirement-before-snapshot",
        existing=["customresourcedefinition||workloads.kueue.x-k8s.io"],
    ),
    "unreadable kueue": lifecycle(
        NAMESPACE, "retirement-before-snapshot", FAKE_UNREADABLE=KUEUE_DEFINITION
    ),
    "held": lifecycle(NAMESPACE, "retirement-before-snapshot"),
    # The reproduction of the review: the snapshot exists and its reads fail.
    "existing snapshot with failing reads": lifecycle(
        NAMESPACE,
        "retirement-before-snapshot",
        FAKE_SNAPSHOT_FOR_EXTERNAL_MANAGER="true",
        FAIL_COMMAND="unmanaged-job-runtime-snapshot",
        TRAINER_HELM_LIFECYCLE_KEEP_FIXTURES="true",
    ),
    "unreadable snapshot": lifecycle(
        NAMESPACE, "retirement-before-snapshot", FAKE_UNREADABLE=HELD_SNAPSHOT
    ),
    "unreadable JobSet": lifecycle(
        NAMESPACE, "retirement-before-snapshot", FAKE_UNREADABLE=HELD_JOB_SET
    ),
    "unreadable definition": lifecycle(
        NAMESPACE,
        "api-upgrade",
        FAIL_COMMAND="crd/trainjobs.trainer.kubeflow.org -o json$",
    ),
    "admitted without runtime": lifecycle(
        NAMESPACE, "retirement-after-snapshot", FAKE_ADMIT_WITHOUT_RUNTIME="true"
    ),
    "connection failure": lifecycle(
        NAMESPACE, "retirement-before-snapshot", FAKE_DENIAL_MESSAGE=CONNECTION_FAILURE
    ),
    "failed rollback": lifecycle(
        NAMESPACE,
        "catalog-update-rollback",
        existing=FOREIGN_OBJECTS,
        FAIL_COMMAND="helm rollback",
    ),
    "kept": lifecycle(
        NAMESPACE, "fixtures", TRAINER_HELM_LIFECYCLE_KEEP_FIXTURES="true"
    ),
    "kept after a failure": lifecycle(
        NAMESPACE,
        "api-reinstall",
        TRAINER_HELM_LIFECYCLE_KEEP_FIXTURES="true",
        FAIL_COMMAND="helm uninstall",
    ),
    "packaged chart": lifecycle(
        NAMESPACE, "api-upgrade", "api-reinstall", TRAINER_APIS_CHART=PACKAGED_CHART
    ),
    "missing chart": lifecycle(
        NAMESPACE, "all", TRAINER_APIS_CHART="/missing/chart.tgz"
    ),
}
for name, (appearing, reads, _) in APPEARING.items():
    RUNS[f"appearing {name}"] = lifecycle(
        NAMESPACE,
        "retirement-before-snapshot",
        FAKE_APPEARING_OBJECT=appearing,
        FAKE_APPEARS_AFTER_READS=str(reads),
    )
for scenario, fragment in UNREAD_ABSENCE_CHECKS.items():
    RUNS[f"unread absence check {scenario}"] = lifecycle(
        NAMESPACE, scenario, FAIL_COMMAND=fragment
    )
for scenario in WITHOUT_EFFECT:
    RUNS[f"without effect {scenario}"] = lifecycle(
        NAMESPACE, scenario, FAKE_UPGRADE_WITHOUT_EFFECT="true"
    )
for position in (0, 2):
    RUNS[f"existing {position}"] = lifecycle(
        NAMESPACE, "fixtures", existing=[FIXTURES[position]]
    )
for position in (0, 1):
    RUNS[f"failed creation {position}"] = lifecycle(
        NAMESPACE, "fixtures", FAIL_COMMAND=f"/{fixture_name(position)}."
    )


def tree_digest(directory):
    digest = hashlib.sha256()
    for path in sorted(Path(directory).rglob("*")):
        digest.update(str(path.relative_to(directory)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def train_job(name):
    return f"trainjob|{NAMESPACE}|{PREFIX}-{name}"


class Run:
    def __init__(self, result, commands, state):
        self.result = result
        self.commands = commands
        self.state = state

    def matching(self, *beginnings):
        return [command for command in self.commands if command.startswith(beginnings)]

    def position(self, fragment):
        (index,) = [
            index for index, line in enumerate(self.commands) if fragment in line
        ]
        return index

    def deleted(self):
        """The identities of the kubectl delete calls, as the fake cluster keys them."""
        identities = []
        for command in self.matching("kubectl delete "):
            words = command.split()
            kind, name = words[2].split("/")
            namespace = (
                words[words.index("--namespace") + 1] if "--namespace" in words else ""
            )
            identities.append(f"{kind}|{namespace}|{name}")
        return identities


class TrainerLifecycleControlFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name).resolve()
        cls.repository = directory / "repository"
        for path in (LIFECYCLE_TEST, INSTALLER, "scripts/library.sh"):
            (cls.repository / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / path, cls.repository / path)
        sdk_test = cls.repository / "tests/trainer_test.sh"
        sdk_test.write_text(
            '#!/usr/bin/env bash\necho "trainer_test.sh $*" >>"$COMMAND_LOG"\n'
        )
        sdk_test.chmod(0o755)
        for chart in ("helm", "helm-crds", "helm-runtimes"):
            shutil.copytree(
                ROOT / "applications/trainer" / chart,
                cls.repository / "applications/trainer" / chart,
            )
        cls.repository_digest = tree_digest(cls.repository)
        cls.packaged_chart = directory / "packaged"
        shutil.copytree(
            cls.repository / "applications/trainer/helm-crds", cls.packaged_chart
        )

        # Both executables import one copy of the fake cluster, which Python
        # compiles once instead of at each of the several hundred calls.
        cls.executables = directory / "executables"
        cls.executables.mkdir()
        shutil.copy2(FAKE_CLUSTER, cls.executables / "fake_cluster.py")
        for name in ("helm", "kubectl"):
            executable = cls.executables / name
            executable.write_text(
                "#!/usr/bin/env python3\nimport sys\n\nimport fake_cluster\n\n"
                f"sys.argv.insert(1, {name!r})\nfake_cluster.main()\n"
            )
            executable.chmod(0o755)

        # The installer itself installs the three releases on the fake cluster,
        # once, and then each release alone, which records its calls.
        cls.installed = directory / "installed"
        cls.installed.mkdir()
        result, cls.complete_installation = cls.run_script(cls.installed, INSTALLER, [])
        assert result.returncode == 0, result.stderr
        cls.installer_commands = {}
        single = directory / "single"
        single.mkdir()
        for release in RELEASES:
            result, cls.installer_commands[release] = cls.run_script(
                single, INSTALLER, [release]
            )
            assert result.returncode == 0, result.stderr

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count())
        cls.addClassCleanup(pool.shutdown)
        cls.runs = {
            name: pool.submit(cls.run_lifecycle, *run) for name, run in RUNS.items()
        }

    @classmethod
    def run_script(cls, directory, script, arguments, variables=None):
        log = directory / "commands"
        log.write_text("")
        inherited = {
            name: value
            for name, value in os.environ.items()
            if not name.startswith(("TRAINER_", "FAKE_"))
            and name not in ("KUBECONFIG", "FAIL_COMMAND", "EVIDENCE_DIRECTORY")
        }
        environment = {
            "PATH": f"{cls.executables}:{os.environ['PATH']}",
            "COMMAND_LOG": str(log),
            "FAKE_CLUSTER_STATE": str(directory / "state.json"),
            "KUBECONFIG": str(directory / "kubeconfig-that-is-never-read"),
            "TRAINER_HELM_LIFECYCLE_DISPOSABLE": "true",
            "TRAINER_HELM_LIFECYCLE_RUN_IDENTIFIER": "control-flow",
            "TRAINER_HELM_LIFECYCLE_SNAPSHOT_ABSENCE_SECONDS": "1",
            "EVIDENCE_DIRECTORY": str(directory / "evidence"),
        }
        result = subprocess.run(
            ["bash", str(cls.repository / script), *arguments],
            env=inherited | environment | (variables or {}),
            cwd=directory,
            text=True,
            capture_output=True,
        )
        return result, log.read_text().splitlines()

    @classmethod
    def run_lifecycle(cls, arguments, existing, variables):
        """Runs the lifecycle test on a fake cluster with the three releases."""
        variables = {
            name: value.replace(PACKAGED_CHART, str(cls.packaged_chart))
            for name, value in variables.items()
        }
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary).resolve()
            state = json.loads((cls.installed / "state.json").read_text())
            for key in existing:
                name = key.split("|")[2]
                state["objects"][key] = {
                    "metadata": {"name": name, "uid": f"foreign-{name}"},
                    "spec": {"runtimeRef": {"name": "team-runtime"}},
                }
            (directory / "state.json").write_text(json.dumps(state))
            result, commands = cls.run_script(
                directory, LIFECYCLE_TEST, arguments, variables
            )
            state = json.loads((directory / "state.json").read_text())
            return Run(result, commands, state)

    def run_of(self, name, passes):
        run = self.runs[name].result()
        self.assertEqual(run.result.returncode == 0, passes, run.result.stderr)
        return run

    def complete_run(self):
        """The run of every scenario, shared by the tests that inspect it."""
        return self.run_of("complete", passes=True)

    def assert_owned_objects_only(self, run, created):
        self.assertEqual(list(run.state["created"]), created)
        self.assertEqual(sorted(run.deleted()), sorted(created))
        self.assertEqual([key for key in run.state["objects"] if PREFIX in key], [])

    def test_no_run_changes_the_checkout(self):
        concurrent.futures.wait(self.runs.values())
        self.assertEqual(tree_digest(self.repository), self.repository_digest)

    def test_refuses_a_cluster_that_is_not_declared_disposable(self):
        for name in ("not disposable", "no kubeconfig"):
            with self.subTest(run=name):
                self.assertEqual(self.run_of(name, passes=False).commands, [])

    def test_an_unknown_scenario_is_refused_before_any_call(self):
        for name in ("unknown scenario", "all with another scenario"):
            with self.subTest(run=name):
                run = self.run_of(name, passes=False)
                self.assertEqual(run.commands, [])
                self.assertIn("is not a scenario", run.result.stderr)

    def test_a_fixture_train_job_name_leaves_room_for_the_pod_name(self):
        # JobSet v0.12.0 denies a JobSet whose Pod names, here
        # <TrainJob>-node-0-0-<5 characters>, exceed 63 characters.
        run = self.run_of("long identifier", passes=False)
        self.assertEqual(run.commands, [])
        self.assertIn("at most 15 characters", run.result.stderr)
        run = self.run_of("default identifier", passes=True)
        names = [key.split("|")[2] for key in run.state["created"]]
        self.assertEqual(len(names), len(FIXTURES))
        for name in names:
            self.assertLessEqual(len(f"{name}-node-0-0-abcde"), 63, name)

    def test_without_a_selection_only_the_smoke_scenario_runs(self):
        for name in ("no argument", "namespace only"):
            with self.subTest(run=name):
                run = self.run_of(name, passes=True)
                self.assertIn("PASS: smoke.", run.result.stdout)
                self.assertEqual(run.matching("helm "), STATUS_CALLS)
                self.assertEqual(run.matching("kubectl delete", "kubectl patch"), [])
                creations = run.matching("kubectl create")
                self.assertEqual(len(creations), 2)
                self.assertTrue(all("--dry-run=server" in line for line in creations))
                self.assertEqual(
                    run.matching("trainer_test.sh"), [f"trainer_test.sh {NAMESPACE}"]
                )
                self.assertEqual(run.state["created"], {})

    def test_the_variable_selects_scenarios_unless_arguments_do(self):
        run = self.run_of("variable", passes=True)
        self.assertIn("PASS: smoke fixtures.", run.result.stdout)
        # Neither scenario changes a release, and the fixtures leave again.
        self.assertEqual(run.matching("helm "), STATUS_CALLS)
        self.assert_owned_objects_only(run, FIXTURES)
        run = self.run_of("argument over variable", passes=True)
        self.assertIn("PASS: smoke.", run.result.stdout)

    def test_every_scenario_passes_and_states_what_it_proves(self):
        run = self.complete_run()
        proved = [
            line.split(":")[1].strip()
            for line in run.result.stdout.splitlines()
            if line.startswith("PROVED: ")
        ]
        self.assertEqual(proved, SCENARIOS)
        self.assertEqual(
            run.matching("trainer_test.sh"), [f"trainer_test.sh {NAMESPACE}"] * 3
        )

    def test_no_call_carries_a_force_option(self):
        run = self.complete_run()
        self.assertGreater(len(run.commands), 100)
        for option in FORCE_OPTIONS:
            self.assertEqual([line for line in run.commands if option in line], [])

    def test_a_complete_run_deletes_exactly_what_it_created(self):
        run = self.complete_run()
        self.assert_owned_objects_only(
            run,
            FIXTURES
            + [train_job(name) for name in ("api-job", "updated-job", "unmanaged-job")],
        )
        for key in FOREIGN_OBJECTS:
            name = key.split("|")[2]
            self.assertEqual(
                run.state["objects"][key]["metadata"]["uid"], f"foreign-{name}"
            )

    def test_a_complete_run_leaves_the_releases_of_this_checkout(self):
        run = self.complete_run()
        self.assertEqual(sorted(run.state["releases"]), sorted(RELEASES))
        objects = run.state["objects"]
        runtime = objects["clustertrainingruntime||torch-distributed"]
        self.assertNotIn("lifecycle", json.dumps(runtime["spec"]))
        definition = objects["customresourcedefinition||trainjobs.trainer.kubeflow.org"]
        self.assertIn("managedBy", json.dumps(definition))
        self.assertNotIn("trainerHelmLifecycleTest", json.dumps(definition))
        deployment = objects["deployment|kubeflow-system|jobset-controller-manager"]
        self.assertNotIn("lifecycle-test", json.dumps(deployment))

    def test_every_reinstallation_issues_the_calls_of_the_installer(self):
        run = self.complete_run()
        by_release = {"trainer": 1, "trainer-apis": 1, "trainer-runtimes": 2}
        # The calls of one release alone are its part of the complete installation.
        preamble = self.complete_installation[:2]
        self.assertEqual(
            self.complete_installation,
            preamble
            + sum((self.installer_commands[release][2:] for release in RELEASES), []),
        )
        for release, count in by_release.items():
            calls = self.installer_commands[release]
            self.assertEqual(calls[:2], preamble)
            self.assertTrue(calls[2].startswith(f"helm install {release} "), calls)
            uninstallations = [
                index
                for index, command in enumerate(run.commands)
                if command.startswith(f"helm uninstall {release} ")
            ]
            self.assertEqual(len(uninstallations), count)
            for uninstallation in uninstallations:
                start = run.commands.index(calls[0], uninstallation)
                self.assertEqual(run.commands[start : start + len(calls)], calls)
                between = run.commands[uninstallation + 1 : start]
                changing = ("helm install", "helm upgrade", "helm rollback")
                self.assertEqual(
                    [command for command in between if command.startswith(changing)], []
                )
        self.assertEqual(len(run.matching("helm install ")), sum(by_release.values()))
        script = (ROOT / LIFECYCLE_TEST).read_text()
        self.assertNotIn("helm install", script)
        self.assertEqual(script.count("./tests/trainer_helm_install.sh "), 3)

    def test_the_changed_charts_are_copies_outside_the_checkout(self):
        run = self.complete_run()
        for release, chart in (
            ("trainer", None),
            ("trainer-apis", "applications/trainer/helm-crds"),
            ("trainer-runtimes", None),
        ):
            charts = [
                command.split()[3]
                for command in run.matching(f"helm upgrade {release} ")
            ]
            self.assertTrue(Path(charts[0]).is_absolute(), charts)
            self.assertNotIn(str(self.repository), charts[0])
            self.assertFalse(Path(charts[0]).exists())
            # The API release returns to the unchanged chart, and the scenario
            # api-reinstall upgrades the reinstalled release with it.
            self.assertEqual(charts[1:], [chart, chart] if chart else [])

    def test_a_changed_definition_upgrade_admits_a_new_train_job(self):
        run = self.complete_run()
        changed, unchanged = [
            index
            for index, command in enumerate(run.commands)
            if command.startswith("helm upgrade trainer-apis ")
        ][:2]
        creation = run.position(f"{PREFIX}-api-job.yaml")
        self.assertLess(changed, creation)
        self.assertLess(creation, unchanged)
        for upgrade in (changed, unchanged):
            following = run.commands[upgrade + 2 : upgrade + 6]
            self.assertTrue(
                all("--for=condition=Established" in command for command in following),
                following,
            )
        self.assertIn(train_job("api-job"), run.state["reconciled"])

    def test_a_catalog_update_is_rolled_back_to_the_revision_before_it(self):
        run = self.complete_run()
        upgrade = run.position("helm upgrade trainer-runtimes ")
        creation = run.position(f"{PREFIX}-updated-job.yaml")
        rollback = run.position(
            "helm rollback trainer-runtimes 1 --namespace kubeflow-system --wait"
        )
        self.assertLess(run.position("helm history trainer-runtimes "), upgrade)
        self.assertLess(upgrade, creation)
        self.assertLess(creation, rollback)
        self.assertIn(train_job("updated-job"), run.state["reconciled"])

    def test_retirement_before_the_first_snapshot(self):
        run = self.complete_run()
        job = f"{PREFIX}-unmanaged-job"
        creation = run.position(f"{job}.yaml")
        retirement = run.commands.index(
            run.matching("helm uninstall trainer-runtimes ")[0], creation
        )
        submission = run.position("new-submission.yaml")
        denied, admitted = [
            run.commands.index(command)
            for command in run.matching(f"kubectl patch trainjob/{job}")
        ]
        restoration = run.commands.index(
            run.matching("helm install trainer-runtimes ")[0], retirement
        )
        self.assertLess(creation, retirement)
        self.assertLess(retirement, submission)
        self.assertLess(submission, denied)
        self.assertLess(denied, restoration)
        self.assertLess(restoration, admitted)
        self.assertNotIn("--dry-run", run.commands[denied])
        self.assertIn("--dry-run=server", run.commands[admitted])
        self.assertIn("--dry-run=server", run.commands[submission])
        manifest = run.state["created"][train_job("unmanaged-job")]
        self.assertEqual(manifest["spec"]["managedBy"], "kueue.x-k8s.io/multikueue")
        self.assertTrue(manifest["spec"]["suspend"])
        self.assertNotIn(train_job("unmanaged-job"), run.state["reconciled"])
        self.assertIn(train_job("catalog-job"), run.state["reconciled"])

    def test_retirement_needs_a_train_job_without_a_snapshot(self):
        run = self.run_of("snapshot for an external manager", passes=False)
        self.assertIn(f"has {HELD_SNAPSHOT} within 1 seconds", run.result.stderr)
        self.assertNotIn("PROVED", run.result.stdout)
        self.assertEqual(run.matching("helm uninstall"), [])

    def test_kueue_or_an_unreadable_kueue_query_refuses_the_scenario(self):
        for name, message in (
            ("kueue", "FAIL: Kueue is installed"),
            ("unreadable kueue", f"{NOT_READ}. The scenario is refused"),
        ):
            with self.subTest(run=name):
                run = self.run_of(name, passes=False)
                self.assertIn(message, run.result.stderr)
                self.assertNotIn("PROVED", run.result.stdout)
                # Refused before the fixtures, so nothing is created or changed.
                self.assertEqual(
                    run.matching("kubectl create", "helm uninstall", "helm install"),
                    [],
                )
                self.assertEqual(run.state["created"], {})

    def test_the_held_train_job_has_no_snapshot_and_no_job_set_in_any_read(self):
        run = self.run_of("held", passes=True)
        self.assertIn("PROVED: retirement-before-snapshot", run.result.stdout)
        self.assertIn("PASS: retirement-before-snapshot.", run.result.stdout)
        snapshot, job_set = (
            ABSENCE_READ.format(resource) for resource in (HELD_SNAPSHOT, HELD_JOB_SET)
        )
        reads = [
            index for index, command in enumerate(run.commands) if command == snapshot
        ]
        # Two passes of the window, one while the runtime is absent, one at the end.
        self.assertEqual(len(reads), 4)
        for index in reads:
            self.assertEqual(run.commands[index + 1], job_set)
        self.assertEqual(run.commands.count(job_set), 4)
        retirement = run.position("helm uninstall trainer-runtimes ")
        restoration = run.position("helm install trainer-runtimes ")
        self.assertLess(reads[1], retirement)
        self.assertLess(retirement, reads[2])
        self.assertLess(reads[2], restoration)
        self.assertLess(restoration, reads[3])
        admitted = run.commands.index(
            run.matching(f"kubectl patch trainjob/{HELD_JOB}")[-1], restoration
        )
        self.assertLess(admitted, reads[3])
        # Nothing but these successful reads establishes the absence: no wait
        # whose failure would pass for it names the held TrainJob.
        self.assertEqual(
            [
                command
                for command in run.matching("kubectl wait")
                if HELD_JOB in command
            ],
            [],
        )
        self.assertEqual([key for key in run.state["objects"] if PREFIX in key], [])

    def test_a_failed_read_of_the_held_train_job_is_not_its_absence(self):
        for name, resource, exists in (
            ("existing snapshot with failing reads", HELD_SNAPSHOT, True),
            ("unreadable snapshot", HELD_SNAPSHOT, False),
            ("unreadable JobSet", HELD_JOB_SET, False),
        ):
            with self.subTest(run=name):
                run = self.run_of(name, passes=False)
                self.assertIn(f"FAIL: {resource} {NOT_READ}", run.result.stderr)
                self.assertNotIn("PROVED", run.result.stdout)
                self.assertNotIn("PASS", run.result.stdout)
                self.assertEqual(run.matching("helm uninstall"), [])
                # Only the reproduction of the review keeps its objects: there the
                # snapshot that the failed reads hid exists.
                key = resource.replace("/", f"|{NAMESPACE}|")
                self.assertEqual(key in run.state["objects"], exists)

    def test_a_snapshot_or_a_job_set_that_appears_fails_the_scenario(self):
        for name, (resource, reads, moment) in APPEARING.items():
            with self.subTest(appearing=name):
                run = self.run_of(f"appearing {name}", passes=False)
                self.assertIn(
                    f"FAIL: The TrainJob {HELD_JOB} has {resource}", run.result.stderr
                )
                self.assertIn(moment, run.result.stderr)
                self.assertNotIn("PROVED", run.result.stdout)
                self.assertNotIn("PASS", run.result.stdout)
                self.assertEqual(
                    run.commands.count(ABSENCE_READ.format(resource)), reads + 1
                )
                # The check that finds it is the one before, during or after the
                # absence of the catalog.
                self.assertEqual(len(run.matching("helm uninstall")), int(reads > 1))
                self.assertEqual(len(run.matching("helm install")), int(reads > 2))
                # The appeared object left with the TrainJob that owns it.
                self.assertEqual(
                    [key for key in run.state["objects"] if PREFIX in key], []
                )

    def test_no_failed_read_counts_as_an_absent_object(self):
        # What must not follow the failed read of a free fixture name, of a webhook
        # configuration after the uninstallation and of the retired runtime.
        never_reached = {
            "fixtures": "kubectl create",
            "controller-reinstall": "helm install",
            "retirement-after-snapshot": "kubectl patch",
        }
        for scenario, call in never_reached.items():
            with self.subTest(scenario=scenario):
                run = self.run_of(f"unread absence check {scenario}", passes=False)
                self.assertIn(NOT_READ, run.result.stderr)
                self.assertNotIn("PROVED", run.result.stdout)
                self.assertEqual(run.matching(call), [])

    def test_an_unreadable_definition_says_nothing_about_its_property(self):
        run = self.run_of("unreadable definition", passes=False)
        self.assertIn(
            "could not be read, which is no evidence about", run.result.stderr
        )
        self.assertNotIn("PROVED", run.result.stdout)
        self.assertEqual(run.matching("helm upgrade"), [])

    def test_only_an_admission_denial_counts_as_a_denial(self):
        for name, message in (
            ("admitted without runtime", "Admitted although"),
            ("connection failure", "not an admission denial"),
        ):
            with self.subTest(run=name):
                run = self.run_of(name, passes=False)
                self.assertIn(message, run.result.stderr)
                self.assertNotIn("PROVED", run.result.stdout)

    def test_an_upgrade_that_does_not_reach_the_live_objects_fails(self):
        for scenario, message in WITHOUT_EFFECT.items():
            with self.subTest(scenario=scenario):
                run = self.run_of(f"without effect {scenario}", passes=False)
                self.assertIn(message, run.result.stderr)
                self.assertNotIn("PROVED", run.result.stdout)
                self.assertEqual(run.matching("helm rollback"), [])
                self.assert_owned_objects_only(run, FIXTURES)

    def test_an_existing_name_is_refused_and_never_deleted(self):
        for position in (0, 2):
            key = FIXTURES[position]
            with self.subTest(existing=key):
                run = self.run_of(f"existing {position}", passes=False)
                self.assertIn("exists already", run.result.stderr)
                self.assertEqual(list(run.state["created"]), FIXTURES[:position])
                self.assertEqual(sorted(run.deleted()), sorted(FIXTURES[:position]))
                self.assertEqual(
                    run.state["objects"][key]["metadata"]["uid"],
                    f"foreign-{fixture_name(position)}",
                )

    def test_a_failed_creation_is_not_owned(self):
        for position in (0, 1):
            with self.subTest(failing=fixture_name(position)):
                run = self.run_of(f"failed creation {position}", passes=False)
                self.assertEqual(len(run.matching("kubectl create")), position + 1)
                self.assertEqual(list(run.state["created"]), FIXTURES[:position])
                self.assertEqual(sorted(run.deleted()), sorted(FIXTURES[:position]))

    def test_a_failure_in_a_scenario_deletes_only_what_the_run_created(self):
        run = self.run_of("failed rollback", passes=False)
        self.assert_owned_objects_only(run, FIXTURES + [train_job("updated-job")])
        for key in FOREIGN_OBJECTS:
            self.assertIn(key, run.state["objects"])

    def test_kept_fixtures_are_not_deleted(self):
        for name, passes in (("kept", True), ("kept after a failure", False)):
            with self.subTest(run=name):
                run = self.run_of(name, passes)
                self.assertEqual(run.matching("kubectl delete"), [])
                self.assertEqual(list(run.state["created"]), FIXTURES)
                for key in FIXTURES:
                    self.assertIn(key, run.state["objects"])

    def test_the_api_chart_variable_reaches_the_installer_and_the_upgrade(self):
        run = self.run_of("packaged chart", passes=True)
        chart = str(self.packaged_chart)
        self.assertEqual(
            [
                command.split()[3]
                for command in run.matching("helm upgrade trainer-apis ")
            ][1:],
            [chart, chart],
        )
        self.assertEqual(
            [command.split()[3] for command in run.matching("helm install ")], [chart]
        )

    def test_a_missing_api_chart_is_refused_before_any_call(self):
        run = self.run_of("missing chart", passes=False)
        self.assertEqual(run.commands, [])
        self.assertIn("TRAINER_APIS_CHART names", run.result.stderr)


if __name__ == "__main__":
    unittest.main()
