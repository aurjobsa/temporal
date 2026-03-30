"""
Worker - Polls task queues and executes workflow and activity tasks.

Reference: https://docs.temporal.io/develop/python/workers

Workers are long-running processes that:
- Poll Temporal Server for work (workflow and activity tasks)
- Execute workflow logic
- Execute activity code
- Report results back to Temporal Server

Key points:
1. Workers connect to Temporal Server
2. They poll specific task queues
3. Multiple workers can process same queue (horizontal scaling)
4. Workers must be running for workflows to execute
5. Activities execute in worker processes
"""

import logging
import asyncio
import os
from typing import Type

from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.common import RetryPolicy
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv()

# Import workflow and activities
from temporal_workflow.workflows import ParallelProcessingWorkflow
from temporal_workflow import activities

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TemporalWorker:
    """
    Wrapper class for Temporal Worker.

    Encapsulates worker setup, lifecycle, and management.

    Reference: Temporal Python SDK - Worker Configuration
    https://docs.temporal.io/develop/python/workers#worker-configuration
    """

    def __init__(
        self,
        namespace: str = "default",
        task_queue: str = "parallel-processing",
        temporal_host: str = "localhost:7233",
        api_key: str = "",
        use_cloud: bool = False,
        max_concurrent_activities: int = 10,
        max_concurrent_workflow_tasks: int = 10,
    ):
        """
        Initialize worker configuration.

        Args:
            namespace: Temporal namespace
            task_queue: Task queue name to process
            temporal_host: Temporal Server host (include port)
            api_key: API key for Temporal Cloud authentication
            use_cloud: Whether to connect to Temporal Cloud (enables TLS + API key)
            max_concurrent_activities: Max activities to run in parallel
            max_concurrent_workflow_tasks: Max workflows to run in parallel
        """
        self.namespace = namespace
        self.task_queue = task_queue
        self.temporal_host = temporal_host
        self.api_key = api_key
        self.use_cloud = use_cloud
        self.max_concurrent_activities = max_concurrent_activities
        self.max_concurrent_workflow_tasks = max_concurrent_workflow_tasks

        self.client: Client = None
        self.worker: Worker = None

        logger.info(
            f"🔧 Worker initialized: namespace={namespace}, "
            f"task_queue={task_queue}, "
            f"server={temporal_host}, "
            f"cloud={use_cloud}"
        )

    async def start(self) -> None:
        """
        Start the worker - connects to Temporal Server and begins polling.

        Reference: Temporal Python SDK - Running a Worker
        https://docs.temporal.io/develop/python/workers#running-a-worker

        This method:
        1. Connects to Temporal Server (local or Cloud)
        2. Creates worker instance
        3. Registers workflows and activities
        4. Starts polling task queue
        5. Runs indefinitely until stopped

        Raises:
            Exception: If connection to Temporal Server fails
        """
        try:
            # ================================================================
            # STEP 1: Connect to Temporal Server
            # ================================================================
            logger.info(
                f"🔗 Connecting to Temporal Server at "
                f"{self.temporal_host}..."
            )

            if self.use_cloud:
                # ---- TEMPORAL CLOUD CONNECTION ----
                self.client = await Client.connect(
                    self.temporal_host,
                    namespace=self.namespace,
                    api_key=self.api_key,
                    tls=True,
                )
                logger.info("✅ Connected to Temporal Cloud")
            else:
                # ---- LOCAL CONNECTION ----
                self.client = await Client.connect(
                    self.temporal_host,
                    namespace=self.namespace,
                )
                logger.info("✅ Connected to Temporal Server (local)")

            # ================================================================
            # STEP 2: Create Worker
            # ================================================================
            logger.info(f"🏗️  Creating worker for task_queue={self.task_queue}...")

            self.worker = Worker(
                self.client,
                task_queue=self.task_queue,
                workflows=[ParallelProcessingWorkflow],
                activities=[
                    # Screening
                    activities.resume_screening_activity,
                    # Voice calls
                    activities.trigger_single_voice_interview_activity,
                    activities.save_voice_call_result,
                    # Emails
                    activities.send_final_emails_activity,
                    # Persistence
                    activities.save_to_supabase,
                    activities.notify_frontend_activity,
                    # Utilities
                    activities.run_meta_pipeline_activity,
                ],
                activity_executor=None,  # Use default executor (ThreadPoolExecutor)
                max_concurrent_activities=self.max_concurrent_activities,
                max_concurrent_workflow_tasks=self.max_concurrent_workflow_tasks,
            )

            logger.info("✅ Worker created")

            # ================================================================
            # STEP 3: Start Worker (begins polling)
            # ================================================================
            logger.info("🚀 Starting worker - polling task queue...")
            logger.info(
                f"📋 Task Queue: {self.task_queue}"
            )
            logger.info(
                f"📊 Max Concurrent Activities: {self.max_concurrent_activities}"
            )
            logger.info(
                f"📊 Max Concurrent Workflows: {self.max_concurrent_workflow_tasks}"
            )

            await self.worker.run()

        except Exception as e:
            logger.error(f"❌ Worker error: {str(e)}")
            raise

    async def stop(self) -> None:
        """
        Stop the worker gracefully.

        Allows in-flight tasks to complete before shutting down.
        """
        logger.info("⏹️  Stopping worker...")

        if self.worker:
            await self.worker.shutdown()
            logger.info("✅ Worker stopped")

        # Client cleanup not explicitly needed in Temporal SDK
        logger.info("✅ Cleanup complete")


async def run_worker(
    namespace: str = None,
    task_queue: str = None,
    temporal_host: str = None,
    api_key: str = None,
    use_cloud: bool = None,
) -> None:
    """
    Main entry point to run the worker.

    Reads configuration from environment variables with fallback defaults.

    Environment Variables:
        TEMPORAL_NAMESPACE: Temporal namespace (default: "default")
        TEMPORAL_TASK_QUEUE: Task queue name (default: "parallel-processing")
        TEMPORAL_HOST: Temporal server address (default: "localhost:7233")
        TEMPORAL_API_KEY: API key for Temporal Cloud
        TEMPORAL_USE_CLOUD: Set to "true" to connect to Temporal Cloud

    Example:
        # Local development
        python -m temporal_workflow.worker.main

        # Temporal Cloud
        TEMPORAL_USE_CLOUD=true python -m temporal_workflow.worker.main
    """
    # Read from env vars with fallbacks
    namespace = namespace or os.environ.get(
        "TEMPORAL_NAMESPACE", "default"
    )
    task_queue = task_queue or os.environ.get(
        "TEMPORAL_TASK_QUEUE", "parallel-processing"
    )
    temporal_host = temporal_host or os.environ.get(
        "TEMPORAL_HOST", "localhost:7233"
    )
    api_key = api_key or os.environ.get(
        "TEMPORAL_API_KEY", ""
    )
    if use_cloud is None:
        use_cloud = os.environ.get(
            "TEMPORAL_USE_CLOUD", "false"
        ).lower() == "true"

    worker = TemporalWorker(
        namespace=namespace,
        task_queue=task_queue,
        temporal_host=temporal_host,
        api_key=api_key,
        use_cloud=use_cloud,
    )

    try:
        logger.info("=" * 70)
        logger.info("🎯 TEMPORAL WORKER STARTING")
        logger.info(f"   ☁️  Cloud Mode: {use_cloud}")
        logger.info(f"   📍 Host: {temporal_host}")
        logger.info(f"   📦 Namespace: {namespace}")
        logger.info("=" * 70)
        await worker.start()
    except KeyboardInterrupt:
        logger.info("\n⚠️  KeyboardInterrupt received")
        await worker.stop()
    except Exception as e:
        logger.error(f"❌ Fatal error: {str(e)}")
        await worker.stop()
        raise


if __name__ == "__main__":
    # Run worker
    asyncio.run(run_worker())