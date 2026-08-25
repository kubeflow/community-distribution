#!/usr/bin/env python3
"""Create a Spark Connect session from inside a Kubeflow Workspace and run a query.

Executed inside the Workspace pod by tests/workspaces_spark_connect_test.sh. The
Workspace runs as its own ServiceAccount ("ws-{WORKSPACE_NAME}"), which the
WorkspaceKind grants "kubeflow-spark-edit" so it can create SparkConnect resources.
"""

import logging
import os
import sys
import pyspark

logger = logging.getLogger("spark_connect_from_workspace")
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

NAMESPACE = os.environ.get("KF_PROFILE", "kubeflow-user-example-com")

from kubeflow.common.types import KubernetesBackendConfig  # noqa: E402
from kubeflow.spark import Name, PodTemplateOverride, SparkClient  # noqa: E402

SESSION_NAME = "spark-connect-workspace-test"

# The Spark driver creates and watches executor pods, so it needs a ServiceAccount
# with those permissions. "default-editor" has them and is what
# applications/spark/sparkapplication_example.yaml already uses for its driver.
DRIVER_SERVICE_ACCOUNT = "default-editor"

# Spark's driver and executors exchange data on ports 7078 and 7079. That traffic
# does not survive the service mesh: executors register with the driver and then
# fail fetching broadcast blocks, so tasks never complete. Both pods are therefore
# excluded from injection, as sparkapplication_example.yaml already does.
NO_SIDECAR = {"sidecar.istio.io/inject": "false"}


def main() -> None:
    client = SparkClient(backend_config=KubernetesBackendConfig(namespace=NAMESPACE))

    logger.info("Creating a Spark Connect session in namespace %s", NAMESPACE)
    spark = None
    try:
        spark = client.connect(
            options=[
                PodTemplateOverride(
                    role="driver",
                    template={
                        "metadata": {"labels": NO_SIDECAR},
                        "spec": {"serviceAccountName": DRIVER_SERVICE_ACCOUNT},
                    },
                ),
                PodTemplateOverride(
                    role="executor",
                    template={
                        "metadata": {"labels": NO_SIDECAR},
                        # Spark submits with executor.podTemplateContainerName=spark-kubernetes-executor
                        # and looks the container up by name, so the template must declare it even
                        # though the operator supplies the image.
                        "spec": {"containers": [{"name": "spark-kubernetes-executor"}]},
                    },
                ),
            ]
        )

        logger.info("Connected to Spark %s (client %s)", spark.version, pyspark.__version__)

        # The shell script pins the client to the SDK's default server version. Assert it
        # held, so a drift shows up as a clear failure rather than an odd protocol error.
        client_minor = pyspark.__version__.rsplit(".", 1)[0]
        assert spark.version.startswith(
            client_minor
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
    finally:
        if spark is not None:
            spark.stop()
        logger.info("Deleting Spark Connect session %s", SESSION_NAME)
        client.delete_session(SESSION_NAME)

    logger.info("Spark Connect session from Workspace verified.")


if __name__ == "__main__":
    main()
