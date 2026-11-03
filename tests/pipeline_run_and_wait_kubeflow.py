#!/usr/bin/env python3

from kfp import dsl
import kfp
from time import monotonic, sleep
import subprocess
import logging
import sys

logger = logging.getLogger("run_and_wait_for_pipeline")
logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


client = kfp.Client()
experiment_name = "my-experiment"
experiment_namespace = "kubeflow-user-example-com"
RUN_TIMEOUT_SECONDS = 5 * 60
POLL_INTERVAL_SECONDS = 10
DIAGNOSTIC_TIMEOUT_SECONDS = 30
RUNNING_STATES = {"PENDING", "RUNNING", "QUEUED"}
FAILED_STATES = {"FAILED", "ERROR", "CANCELED", "CANCELLED", "SKIPPED"}


@dsl.component
def add(a: float, b: float) -> float:
    """Calculates sum of two arguments"""
    return a + b


@dsl.pipeline(
    name="Addition pipeline",
    description="An example pipeline that performs addition calculations.",
)
def add_pipeline(
    a: float = 1.0,
    b: float = 7.0,
):
    first_add_task = add(a=a, b=4.0)
    add(a=first_add_task.output, b=b)


def normalize_state(state):
    if state is None:
        return "UNKNOWN"
    return str(state).split(".")[-1].upper()


def get_run_state(live_run):
    state = getattr(live_run, "state", None)
    if state is not None:
        return normalize_state(state)

    run = getattr(live_run, "run", None)
    if run is not None:
        status = getattr(run, "status", None)
        if status is not None:
            return normalize_state(status)

    return "UNKNOWN"


def dump_pipeline_diagnostics():
    diagnostic_commands = [
        [
            "kubectl",
            "-n",
            experiment_namespace,
            "get",
            "workflows.argoproj.io,pods",
            "-o",
            "wide",
        ],
        ["kubectl", "-n", experiment_namespace, "describe", "workflows.argoproj.io"],
        [
            "kubectl",
            "-n",
            experiment_namespace,
            "get",
            "events",
            "--sort-by=.lastTimestamp",
        ],
    ]

    for command in diagnostic_commands:
        logger.warning("Running diagnostic command: %s", " ".join(command))
        try:
            subprocess.run(
                command,
                check=False,
                timeout=DIAGNOSTIC_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "Diagnostic command timed out after %s seconds.",
                DIAGNOSTIC_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            logger.warning(
                "Unable to run diagnostics because kubectl is not available."
            )
            return
        except Exception as e:
            logger.warning(
                "Unable to run diagnostic command. Exception: %s: %s",
                e.__class__.__name__,
                str(e),
            )


def fail_pipeline_run(message, live_run=None):
    logger.error(message)
    if live_run is not None:
        try:
            logger.error("Pipeline Run State: %s.", get_run_state(live_run))
        except Exception as e:
            logger.error(
                "Unable to extract Pipeline Run State. Exception: %s: %s",
                e.__class__.__name__,
                str(e),
            )
        try:
            run_error = getattr(live_run, "error", None)
        except Exception as e:
            logger.error(
                "Unable to extract Pipeline Run error. Exception: %s: %s",
                e.__class__.__name__,
                str(e),
            )
            run_error = None
        if run_error:
            logger.error("Pipeline Run error: %s.", run_error)
    dump_pipeline_diagnostics()
    raise SystemExit(1)


try:
    logger.info(
        f"Trying to get experiment from {experiment_name=} {experiment_namespace=}."
    )
    experiment = client.get_experiment(
        experiment_name=experiment_name, namespace=experiment_namespace
    )
    logger.info("Experiment found!")
except Exception:
    logger.info("Experiment not found, trying to create experiment.")
    experiment = client.create_experiment(
        name=experiment_name, namespace=experiment_namespace
    )
    logger.info("Experiment created!")

try:
    logger.info("Trying to create Pipeline Run.")
    run = client.create_run_from_pipeline_func(
        add_pipeline,
        arguments={"a": 7.0, "b": 8.0},
        experiment_id=experiment.experiment_id,
        enable_caching=False,
    )
except Exception as e:
    logger.error(
        f"Failed to create Pipeline Run. Exception: {e.__class__.__name__}: {str(e)}"
    )
    raise SystemExit(1)

deadline = monotonic() + RUN_TIMEOUT_SECONDS
last_live_run = None
while monotonic() < deadline:
    try:
        live_run = client.get_run(run_id=run.run_id)
    except Exception as e:
        fail_pipeline_run(
            "Failed to get Pipeline Run. "
            f"Exception: {e.__class__.__name__}: {str(e)}"
        )
    last_live_run = live_run

    try:
        run_state = get_run_state(live_run)
    except Exception as e:
        fail_pipeline_run(
            "Failed to extract Pipeline Run state. "
            f"Exception: {e.__class__.__name__}: {str(e)}",
            live_run,
        )
    logger.info("Pipeline Run State: %s.", run_state)

    if run_state == "SUCCEEDED":
        logger.info("Finished Pipeline Run successfully.")
        break

    if run_state in FAILED_STATES or run_state not in RUNNING_STATES:
        fail_pipeline_run("Pipeline Run finished but did not succeed.", live_run)

    logger.info("Waiting for pipeline to finish...")
    remaining_seconds = deadline - monotonic()
    if remaining_seconds > 0:
        sleep(min(POLL_INTERVAL_SECONDS, remaining_seconds))
else:
    fail_pipeline_run(
        f"Pipeline Run did not finish within {RUN_TIMEOUT_SECONDS} seconds.",
        last_live_run,
    )
