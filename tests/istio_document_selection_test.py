#!/usr/bin/env python3
"""Execute the Istio synchronization script's document selector.

The selector splits a Kustomize render into a Namespace payload and everything
else. It replaced a positional `sed '1,/^---$/d'`, so the cases that matter are
the ones where a separator or a kind line is not exactly what was expected: a
document that would be misread merges into its neighbour and the payload is
silently wrong.
"""

import subprocess
import textwrap
import unittest
from pathlib import Path

ROOT_DIRECTORY = Path(__file__).resolve().parents[1]
SYNCHRONIZATION_SCRIPT = ROOT_DIRECTORY / "scripts/synchronize-istio-manifests.sh"

NAMESPACE_DOCUMENT = textwrap.dedent("""\
    apiVersion: v1
    kind: Namespace
    metadata:
      name: istio-system
    """)
POLICY_DOCUMENT = textwrap.dedent("""\
    apiVersion: networking.k8s.io/v1
    kind: NetworkPolicy
    metadata:
      name: allow-istiod
    """)


def select(stream, selection, kind):
    """Run select_manifest_documents from the synchronization script."""
    script = textwrap.dedent(f"""\
        set -euo pipefail
        # Load only the selector, not the synchronization script's side effects.
        eval "$(sed -n '/^select_manifest_documents()/,/^}}$/p' {SYNCHRONIZATION_SCRIPT})"
        select_manifest_documents "{selection}" "{kind}"
        """)
    result = subprocess.run(
        ["bash", "-c", script],
        input=stream,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return result.stdout


class DocumentSelectionTest(unittest.TestCase):
    def test_splits_a_plain_stream(self):
        stream = NAMESPACE_DOCUMENT + "---\n" + POLICY_DOCUMENT

        self.assertIn("kind: Namespace", select(stream, "only", "Namespace"))
        self.assertNotIn("kind: NetworkPolicy", select(stream, "only", "Namespace"))
        self.assertIn("kind: NetworkPolicy", select(stream, "except", "Namespace"))
        self.assertNotIn("kind: Namespace", select(stream, "except", "Namespace"))

    def test_separator_with_carriage_return(self):
        """A CRLF stream must not merge both documents into one buffer."""
        stream = NAMESPACE_DOCUMENT + "---\r\n" + POLICY_DOCUMENT

        self.assertNotIn("kind: NetworkPolicy", select(stream, "only", "Namespace"))
        self.assertIn("kind: NetworkPolicy", select(stream, "except", "Namespace"))

    def test_separator_with_trailing_whitespace(self):
        stream = NAMESPACE_DOCUMENT + "---   \n" + POLICY_DOCUMENT

        self.assertNotIn("kind: NetworkPolicy", select(stream, "only", "Namespace"))
        self.assertIn("kind: NetworkPolicy", select(stream, "except", "Namespace"))

    def test_separator_with_a_comment(self):
        """--- # comment is a valid YAML directives-end marker."""
        stream = NAMESPACE_DOCUMENT + "--- # the policies\n" + POLICY_DOCUMENT

        self.assertNotIn("kind: NetworkPolicy", select(stream, "only", "Namespace"))
        self.assertIn("kind: NetworkPolicy", select(stream, "except", "Namespace"))

    def test_three_dashes_followed_by_a_comment_character_is_content(self):
        """YAML needs a blank before a comment, so ---#text is scalar content."""
        stream = textwrap.dedent("""\
            kind: ConfigMap
            data:
              value: "first
            ---#inside
            last"
            """)

        selected = select(stream, "except", "Namespace")
        self.assertIn("---#inside", selected)
        self.assertNotIn("\n---\n", selected)

    def test_kind_only_matches_at_the_top_level(self):
        """An indented or commented kind must not decide the document."""
        stream = textwrap.dedent("""\
            apiVersion: apiextensions.k8s.io/v1
            kind: CustomResourceDefinition
            metadata:
              name: things.example.com
            spec:
              names:
                kind: Namespace
            """)

        self.assertEqual(select(stream, "only", "Namespace").strip(), "")
        self.assertIn(
            "kind: CustomResourceDefinition", select(stream, "except", "Namespace")
        )

    def test_a_document_without_a_kind_is_not_selected(self):
        stream = "# just a comment\n---\n" + NAMESPACE_DOCUMENT

        selected = select(stream, "only", "Namespace")
        self.assertIn("kind: Namespace", selected)
        self.assertNotIn("just a comment", selected)

    def test_every_document_lands_on_exactly_one_side(self):
        stream = NAMESPACE_DOCUMENT + "---\n" + POLICY_DOCUMENT
        only = select(stream, "only", "Namespace")
        rest = select(stream, "except", "Namespace")

        for line in ("kind: Namespace", "kind: NetworkPolicy"):
            self.assertEqual(
                (line in only) + (line in rest), 1, f"{line} must appear exactly once"
            )


if __name__ == "__main__":
    unittest.main()
