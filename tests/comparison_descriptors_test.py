#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

import yaml

import run_helm_kustomize_comparison as comparison

WORKFLOW_PATH = (
    comparison.ROOT_DIRECTORY / ".github/workflows/helm-kustomize-comparison.yml"
)


class DescriptorTest(unittest.TestCase):
    """Guards over the descriptors this repository actually ships."""

    @classmethod
    def setUpClass(cls):
        cls.descriptors = comparison.discover()

    def test_every_chart_declares_how_it_is_compared(self):
        """Discovery skips a chart with no descriptor, so nothing else would.

        Without this, a contributor can add a chart, omit one file, and get a
        green build with no parity coverage at all.
        """
        for pattern in comparison.CHART_GLOBS:
            for chart in comparison.ROOT_DIRECTORY.glob(pattern):
                if not (chart / "Chart.yaml").is_file():
                    continue
                with self.subTest(
                    chart=str(chart.relative_to(comparison.ROOT_DIRECTORY))
                ):
                    self.assertTrue(
                        (chart / "ci" / "comparison.yaml").is_file(),
                        "every chart must declare ci/comparison.yaml so it is compared",
                    )

    def test_declared_paths_exist(self):
        """A typo would otherwise surface as an opaque kustomize build error."""
        for component, (chart, descriptor) in self.descriptors.items():
            for name, scenario in descriptor["scenarios"].items():
                with self.subTest(component=component, scenario=name):
                    for path in scenario["kustomize"]:
                        self.assertTrue(
                            (comparison.ROOT_DIRECTORY / path).is_dir(), path
                        )
                    if scenario.get("values"):
                        self.assertTrue((chart / scenario["values"]).is_file())


class MalformedDescriptorTest(unittest.TestCase):
    """A descriptor decides what is compared, so a broken one must not load."""

    def load(self, body):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "comparison.yaml"
            path.write_text("component: x\nreleaseName: x\nnamespace: n\n" + body)
            return comparison.load_descriptor(path)

    def test_a_repeated_scenario_name_is_rejected(self):
        """PyYAML keeps the last duplicate, silently dropping parity coverage."""
        with self.assertRaises(Exception) as error:
            self.load(
                "scenarios:\n  a:\n    kustomize: [x]\n  a:\n    kustomize: [y]\n"
            )
        self.assertIn("duplicate key", str(error.exception))

    def test_a_scenario_without_kustomize_targets_is_rejected(self):
        with self.assertRaises(ValueError):
            self.load("scenarios:\n  a:\n    values: v.yaml\n")

    def test_a_default_scenario_that_is_not_declared_is_rejected(self):
        """Katib's old default was 'base', a scenario Katib does not have, so
        comparing it without naming one could only ever fail."""
        with self.assertRaises(ValueError):
            self.load(
                "defaultScenario: base\n"
                "scenarios:\n  standalone:\n    kustomize: [x]\n"
                "  platform:\n    kustomize: [y]\n"
            )


class MalformedAllowanceTest(unittest.TestCase):
    """An allowance weakens the comparison, so a malformed one must not load.

    Every rejection here is a mistake the code-based exceptions made possible:
    unscoped rules, rules with no recorded reason, and typos that would have
    silently matched nothing.
    """

    def load(self, body):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "comparison.yaml"
            path.write_text(
                "component: x\nreleaseName: x\nnamespace: n\n"
                "scenarios:\n  a:\n    kustomize: [x]\n" + body
            )
            return comparison.load_descriptor(path)

    def test_a_missing_reason_is_rejected_in_every_family(self):
        for family, body in {
            "ignoredLabels": "ignoredLabels:\n- keys: [a]\n",
            "knownDifferences": "knownDifferences:\n- skip: Namespace/x\n",
            "helmOnlyResources": "helmOnlyResources:\n- resource: Secret/x\n",
        }.items():
            with self.subTest(family=family):
                with self.assertRaises(ValueError) as error:
                    self.load(body)
                self.assertIn("reason", str(error.exception))

    def test_a_pattern_with_the_wrong_shape_is_rejected(self):
        for pattern in ("Deployment", "a/b/c/d", "Deployment//x"):
            with self.subTest(pattern=pattern):
                with self.assertRaises(ValueError):
                    self.load("knownDifferences:\n" f"- skip: {pattern}\n  reason: r\n")

    def test_a_misspelled_action_is_rejected(self):
        """An unknown field would otherwise declare an allowance that does
        nothing, which the old code allowed and nothing detected."""
        with self.assertRaises(ValueError) as error:
            self.load(
                "knownDifferences:\n"
                "- resource: Deployment/auth/dex\n"
                "  ignorePodTemplateAnnotation: [checksum/config]\n"
                "  reason: r\n"
            )
        self.assertIn("unknown", str(error.exception))

    def test_an_entry_without_any_action_is_rejected(self):
        with self.assertRaises(ValueError):
            self.load(
                "knownDifferences:\n- resource: Deployment/auth/dex\n  reason: r\n"
            )

    def test_an_ignored_labels_entry_without_keys_is_rejected(self):
        with self.assertRaises(ValueError):
            self.load("ignoredLabels:\n- reason: r\n")

    def test_a_skip_entry_with_extra_fields_is_rejected(self):
        with self.assertRaises(ValueError):
            self.load(
                "knownDifferences:\n"
                "- skip: Namespace/x\n  compareDataAsYaml: [a]\n  reason: r\n"
            )

    def test_a_retained_definition_block_needs_names_and_a_reason(self):
        for body in (
            "retainedCustomResourceDefinitions:\n- a.example.com\n",
            "retainedCustomResourceDefinitions:\n  names: [a.example.com]\n",
            "retainedCustomResourceDefinitions:\n  reason: r\n  names: []\n",
        ):
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    self.load(body)

    def test_the_base_body_alone_loads(self):
        """Every rejection above must be attributable to the malformed
        allowance, not to the shared boilerplate."""
        self.load("")

    def test_an_empty_only_kinds_list_is_rejected(self):
        """An empty onlyKinds would compare nothing and still report success."""
        with self.assertRaises(ValueError):
            self.load_with_scenario_field("onlyKinds: []")

    def load_with_scenario_field(self, field):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "comparison.yaml"
            path.write_text(
                "component: x\nreleaseName: x\nnamespace: n\n"
                f"scenarios:\n  a:\n    kustomize: [x]\n    {field}\n"
            )
            return comparison.load_descriptor(path)


class WorkflowTest(unittest.TestCase):
    """The comparison is only a check if it can fail a pull request."""

    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(WORKFLOW_PATH.read_text())

    def test_the_matrix_is_discovered_not_listed(self):
        """A hand-written component list is what this design removed.

        Kubeflow Pipelines was registered everywhere except a blocking job, and
        nothing noticed, because an incomplete list looks like a complete one.
        """
        matrix = self.workflow["jobs"]["compare"]["strategy"]["matrix"]["component"]
        self.assertIn("fromJSON(needs.discover-components.outputs.components)", matrix)

    def test_no_job_is_advisory(self):
        """'Compare All Scenarios' carried continue-on-error: true, so seven of
        the ten components had no blocking parity check at all."""
        for name, job in self.workflow["jobs"].items():
            with self.subTest(job=name):
                self.assertFalse(job.get("continue-on-error", False))
                for step in job["steps"]:
                    self.assertFalse(step.get("continue-on-error", False))

    def test_the_comparison_cannot_be_skipped(self):
        """A conditional step passes by not running, which reads as success."""
        for step in self.workflow["jobs"]["compare"]["steps"]:
            with self.subTest(step=step["name"]):
                self.assertNotIn("if", step)

    def test_the_comparison_job_puts_kustomize_on_the_path(self):
        """Installing kustomize without exporting the path fails at render time,
        far from the step that caused it."""
        commands = "\n".join(
            step.get("run", "") for step in self.workflow["jobs"]["compare"]["steps"]
        )
        self.assertIn("./tests/kustomize_install.sh", commands)
        self.assertIn('echo "/tmp/usr/local/bin" >> "$GITHUB_PATH"', commands)


if __name__ == "__main__":
    unittest.main()
