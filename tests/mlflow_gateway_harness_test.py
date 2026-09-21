#!/usr/bin/env python3
"""Check gateway test assertions and cleanup without claiming runtime coverage."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

COMMAND = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

arguments = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a") as stream:
    stream.write(json.dumps([Path(sys.argv[0]).name, arguments]) + "\n")
if Path(sys.argv[0]).name == "sleep":
    sys.exit(0)
if Path(sys.argv[0]).name == "kubectl":
    if arguments[:2] == ["create", "--raw"]:
        review = json.load(sys.stdin)
        assert arguments[2] == "/apis/authorization.k8s.io/v1/subjectaccessreviews"
        assert review["spec"] == {
            "user": "system:serviceaccount:mlflow-isolation-owned:default-editor",
            "resourceAttributes": {
                "group": "mlflow.kubeflow.org",
                "resource": "experiments",
                "verb": "create",
                "namespace": "mlflow-isolation-owned",
            },
        }
        print(json.dumps({"status": {"allowed": os.environ.get("FAILURE") != "readiness"}}))
    elif arguments[:2] == ["create", "-f"]:
        sys.stdin.read()
        print("mlflow-isolation-owned", end="")
    elif "token" in arguments:
        print(arguments[1] + ":" + arguments[-1], end="")
    sys.exit(0)

headers = [arguments[index + 1] for index, value in enumerate(arguments) if value == "-H"]
token = next((header.split(": ", 1)[1] for header in headers if header.startswith("Authorization:")), "")
workspace = next((header.split(": ", 1)[1] for header in headers if header.startswith("X-MLFLOW-WORKSPACE:")), "")
own = "mlflow-isolation-owned" if "mlflow-isolation-owned" in token else "profile-existing"
other = "profile-existing" if own == "mlflow-isolation-owned" else "mlflow-isolation-owned"
identifier = "2" if own == "mlflow-isolation-owned" else "1"
url = next(argument for argument in arguments if argument.startswith("http://"))
status, payload = 200, {}
if not token:
    status = 302
elif url.endswith("/search") and json.loads(arguments[arguments.index("-d") + 1]).get("max_results", 0) <= 0:
    status = 400
    payload = {"error_code": "INVALID_PARAMETER_VALUE", "message": "max_results must be positive"}
elif url.endswith("/health"):
    payload = "OK"
elif url.endswith("/workspaces"):
    payload = {"workspaces": [{"name": own}]}
    if os.environ.get("FAILURE") == "discovery":
        payload["workspaces"].append({"name": other})
elif workspace == "default":
    status = 404
elif "default:default" in token:
    status = 403
elif workspace != own:
    if url.endswith("/search"):
        payload = {"experiments": []}
        if os.environ.get("FAILURE") == "collection":
            payload["experiments"].append({"experiment_id": "leaked"})
    elif os.environ.get("FAILURE") == "spoof" and any(header.startswith("kubeflow-userid:") for header in headers):
        payload = {"experiment_id": "forged"}
    else:
        status = 403
elif url.endswith("/create"):
    if "default-viewer" in token:
        status = 403
    else:
        payload = {"experiment_id": identifier}
elif url.endswith("/search"):
    payload = {"experiments": [{"experiment_id": identifier}]}
    if os.environ.get("FAILURE") == "viewer":
        payload = {"experiments": []}
elif "/get?" in url:
    payload = {"experiment": {"experiment_id": identifier}}
Path(arguments[arguments.index("-o") + 1]).write_text(json.dumps(payload))
if "-w" in arguments:
    print(status, end="")
"""


class MLflowGatewayHarnessTest(unittest.TestCase):
    def run_scenario(self, failure=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("kubectl", "curl", "sleep"):
                command = root / name
                command.write_text(COMMAND)
                command.chmod(0o755)
            command_log = root / "commands.jsonl"
            result = subprocess.run(
                [
                    "bash",
                    str(Path(__file__).with_name("mlflow_test.sh")),
                    "profile-existing",
                ],
                env={
                    **os.environ,
                    "PATH": f"{directory}:{os.environ['PATH']}",
                    "COMMAND_LOG": str(command_log),
                    "FAILURE": failure,
                },
                capture_output=True,
                text=True,
                timeout=30,
            )
            commands = [
                json.loads(line) for line in command_log.read_text().splitlines()
            ]
            profile_deletions = [
                arguments
                for name, arguments in commands
                if name == "kubectl" and arguments[:2] == ["delete", "profile"]
            ]
            self.assertEqual(
                [
                    [
                        "delete",
                        "profile",
                        "mlflow-isolation-owned",
                        "--wait=true",
                        "--timeout=120s",
                    ]
                ],
                profile_deletions,
            )
            return result, commands

    def test_successful_contract_and_owned_profile_cleanup(self):
        result, _ = self.run_scenario()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_virtual_resource_readiness_uses_explicit_subject_access_review(self):
        result, commands = self.run_scenario()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(
            any(
                name == "kubectl"
                and arguments[:3]
                == [
                    "create",
                    "--raw",
                    "/apis/authorization.k8s.io/v1/subjectaccessreviews",
                ]
                for name, arguments in commands
            ),
            "Virtual MLflow resources require an explicit authorization API group",
        )

    def test_denied_readiness_fails_and_cleans_up(self):
        result, _ = self.run_scenario("readiness")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Profile editor permissions did not reconcile", result.stderr)

    def test_search_requests_specify_positive_maximum_results(self):
        result, commands = self.run_scenario()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        for name, arguments in commands:
            if name == "curl" and any(
                argument.endswith("/search") for argument in arguments
            ):
                request_body = json.loads(arguments[arguments.index("-d") + 1])
                self.assertGreater(request_body.get("max_results", 0), 0)

    def test_security_regressions_fail_and_still_clean_up(self):
        for failure in ("discovery", "collection", "viewer", "spoof"):
            with self.subTest(failure=failure):
                result, _ = self.run_scenario(failure)
                self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
