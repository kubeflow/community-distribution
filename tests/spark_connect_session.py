#!/usr/bin/env python3
"""Create a Spark Connect session from inside a Kubeflow notebook pod and run a query.

Shared by two tests, which copy this file into their pod and run it there:
tests/workspaces_spark_connect_test.sh and tests/notebooks_spark_connect_test.sh.
Creating the session is identical from either, so keep this file host-agnostic — only
the way the pod's ServiceAccount gets "kubeflow-spark-edit" differs, and that lives in
the shell scripts. A Workspace runs as "ws-{WORKSPACE_NAME}" and its WorkspaceKind has
to request the grant; a Notebook runs as "default-editor", which a Profile already binds
to the aggregated "kubeflow-edit".
"""

import logging
import os
import sys
import pyspark

logger = logging.getLogger("spark_connect_session")
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

NAMESPACE = os.environ.get("KF_PROFILE", "kubeflow-user-example-com")

from kubeflow.common.types import KubernetesBackendConfig  # noqa: E402
from kubeflow.spark import (  # noqa: E402
    Driver,
    Labels,
    Name,
    PodTemplateOverride,
    SparkClient,
)

SESSION_NAME = "spark-connect-workspace-test"

# The Spark driver creates and watches executor pods, so it needs a ServiceAccount
# with those permissions. "default-editor" has them and is what
# applications/spark/sparkapplication_example.yaml already uses for its driver.
DRIVER_SERVICE_ACCOUNT = "default-editor"

# Spark's driver and executors exchange data on ports 7078 and 7079, and the client
# reaches the server over gRPC. None of that survives the service mesh, so both pods are
# excluded from injection, as sparkapplication_example.yaml already does. This is an
# upstream Spark-on-Kubernetes limitation (SPARK-42411).
#
# The two pods need the label by different routes. Executors are created by spark-submit,
# so the operator turns the SparkConnect labels into
# "spark.kubernetes.executor.label.*" and Labels() is enough. The server pod is built by
# the operator itself, and it takes its labels only from the server pod template
# (internal/controller/sparkconnect/reconciler.go), so that one needs an override.
NO_SIDECAR = {"sidecar.istio.io/inject": "false"}


def main() -> None:
    client = SparkClient(backend_config=KubernetesBackendConfig(namespace=NAMESPACE))

    logger.info("Creating a Spark Connect session in namespace %s", NAMESPACE)
    spark = client.connect(
        driver=Driver(service_account=DRIVER_SERVICE_ACCOUNT),
        options=[
            Name(SESSION_NAME),
            Labels(NO_SIDECAR),
            PodTemplateOverride(
                role="driver",
                template={"metadata": {"labels": NO_SIDECAR}},
            ),
        ],
    )

    logger.info("Connected to Spark %s (client %s)", spark.version, pyspark.__version__)

    # The shell script pins the client to the SDK's default server version. Assert it
    # held, so a drift shows up as a clear failure rather than an odd protocol error.
    client_major_minor = pyspark.__version__.rsplit(".", 1)[0]
    assert spark.version.startswith(
        client_major_minor
    ), f"client {pyspark.__version__} and server {spark.version} major.minor differ"

    # A grouped aggregation rather than a plain count, so the work is distributed
    # across executors and the driver-executor block transfer is exercised.
    rows = (
        spark.range(0, 100_000, numPartitions=4)
        .selectExpr("id % 8 AS bucket")
        .groupBy("bucket")
        .count()
        .collect()
    )

    total = sum(row["count"] for row in rows)
    logger.info("Aggregated %s rows into %s buckets", total, len(rows))

    assert len(rows) == 8, f"expected 8 buckets, got {len(rows)}"
    assert total == 100_000, f"expected 100000 rows, got {total}"

    spark.stop()

    logger.info("Deleting Spark Connect session %s", SESSION_NAME)
    client.delete_session(SESSION_NAME)

    logger.info("Spark Connect session from Workspace verified.")


if __name__ == "__main__":
    main()
