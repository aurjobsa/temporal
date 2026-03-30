"""
Client - Starts and communicates with workflows.

Reference: https://docs.temporal.io/develop/python/clients

The client is used to:
- Start workflow executions
- Send signals to running workflows
- Query workflow state
- Wait for completion
- Handle results

Key points:
1. Client connects to Temporal Server
2. Can start workflows and get back a workflow handle
3. Can send signals to running workflows
4. Can wait for workflow completion
5. Multiple clients can interact with same workflow
"""

import logging
import os
from typing import Any, Dict, Optional
from datetime import timedelta
import asyncio

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

# Import models and workflow
from temporal_workflow.models import WorkflowInput, WorkflowStep, WorkflowOutput, StepResult
from temporal_workflow.workflows import ParallelProcessingWorkflow

# Configure logging
logger = logging.getLogger(__name__)


class TemporalClient:
    """
    Wrapper class for Temporal Client.

    Provides high-level interface for starting workflows and managing execution.

    Reference: Temporal Python SDK - Client Configuration
    https://docs.temporal.io/develop/python/clients#client-configuration
    """

    def __init__(
        self,
        namespace: str = "default",
        temporal_host: str = "localhost:7233",
        api_key: str = "",
        use_cloud: bool = False,
    ):
        """
        Initialize client configuration.

        Args:
            namespace: Temporal namespace
            temporal_host: Temporal Server host (include port)
            api_key: API key for Temporal Cloud authentication
            use_cloud: Whether to connect to Temporal Cloud (enables TLS + API key)
        """
        self.namespace = namespace
        self.temporal_host = temporal_host
        self.api_key = api_key
        self.use_cloud = use_cloud
        self.client: Client = None

        logger.info(
            f"🔧 Temporal Client initialized: namespace={namespace}, "
            f"server={temporal_host}, cloud={use_cloud}"
        )

    async def connect(self) -> None:
        """
        Connect to Temporal Server (local or Cloud).

        Reference: Temporal Python SDK - Connecting to Temporal
        https://docs.temporal.io/develop/python/clients#connecting-to-temporal

        Raises:
            Exception: If connection fails
        """
        try:
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

        except Exception as e:
            logger.error(f"❌ Connection failed: {str(e)}")
            raise

    async def close(self) -> None:
        """Close client connection."""
        logger.info("✅ Client connection closed")

    async def start_orchestration(
        self,
        chat_id: str,
        tenant_id: str,
        steps: list,
        workflow_id: Optional[str] = None,
        task_queue: str = "parallel-processing",
    ) -> str:
        """
        Start a new orchestration workflow.

        Reference: Temporal Python SDK - Starting Workflows
        https://docs.temporal.io/develop/python/clients#starting-workflows

        This method:
        1. Creates workflow input data
        2. Starts workflow execution
        3. Returns workflow ID for later reference

        Args:
            chat_id: Conversation identifier
            tenant_id: Tenant identifier
            steps: List of WorkflowStep objects
            workflow_id: Optional custom workflow ID (auto-generated if not provided)
            task_queue: Task queue to use (must match worker's queue)

        Returns:
            Workflow execution ID

        Raises:
            WorkflowAlreadyStartedError: If workflow with same ID already exists
            Exception: If workflow start fails
        """
        try:
            # ================================================================
            # STEP 1: Build workflow input
            # ================================================================
            workflow_input = WorkflowInput(
                chat_id=chat_id,
                tenant_id=tenant_id,
                steps=steps,
            )

            logger.info(f"📋 Starting orchestration workflow")
            logger.info(f"   💬 Chat ID: {chat_id}")
            logger.info(f"   🏢 Tenant ID: {tenant_id}")
            logger.info(f"   📊 Steps: {len(steps)}")

            # ================================================================
            # STEP 2: Start workflow
            # ================================================================
            # If no workflow_id provided, Temporal will generate one
            workflow_execution_id = workflow_id or f"orchestration-{chat_id}"

            logger.info(f"🚀 Starting workflow: {workflow_execution_id}")

            # Start workflow and get handle (don't wait for completion)
            handle = await self.client.start_workflow(
                ParallelProcessingWorkflow.orchestrate,
                arg=workflow_input,
                id=workflow_execution_id,
                task_queue=task_queue,
                # Execution timeout (total time workflow can run)
                execution_timeout=timedelta(hours=24),
                # Run timeout (time between heartbeats)
                run_timeout=timedelta(hours=1),
            )

            logger.info(f"✅ Workflow started: {handle.id}")
            logger.info(f"   🔗 Workflow ID: {handle.id}")
            logger.info(f"   📊 Run ID: {handle.run_id}")

            return handle.id

        except WorkflowAlreadyStartedError:
            logger.error(
                f"❌ Workflow with ID {workflow_execution_id} already exists"
            )
            raise
        except Exception as e:
            logger.error(f"❌ Failed to start workflow: {str(e)}")
            raise

    async def wait_for_workflow(
        self,
        workflow_id: str,
    ) -> WorkflowOutput:
        """
        Wait for workflow to complete and get result.

        Reference: Temporal Python SDK - Waiting for Workflows
        https://docs.temporal.io/develop/python/clients#waiting-for-workflow-completion

        This method:
        1. Gets workflow handle
        2. Waits for completion
        3. Returns workflow output

        Args:
            workflow_id: Workflow execution ID

        Returns:
            WorkflowOutput with results

        Raises:
            Exception: If workflow fails or times out
        """
        try:
            logger.info(f"⏳ Waiting for workflow {workflow_id} to complete...")

            # Get handle to running workflow
            handle = self.client.get_workflow_handle(workflow_id)

            # Wait for result (blocks until completion or timeout)
            result = await handle.result(rpc_timeout=timedelta(hours=24))

            # Convert dict result to WorkflowOutput object
            if isinstance(result, dict):
                # Convert nested step_results dicts to StepResult objects
                step_results = {}
                for step_id, step_result in result.get("step_results", {}).items():
                    if isinstance(step_result, dict):
                        step_results[step_id] = StepResult(**step_result)
                    else:
                        step_results[step_id] = step_result

                result = WorkflowOutput(
                    workflow_run_id=result.get("workflow_run_id", ""),
                    chat_id=result.get("chat_id", ""),
                    status=result.get("status", "unknown"),
                    step_results=step_results,
                    summary=result.get("summary", {}),
                )

            logger.info(f"✅ Workflow completed: {workflow_id}")
            logger.info(f"   📊 Status: {result.status}")
            logger.info(f"   📋 Completed steps: {len(result.step_results)}")

            return result

        except Exception as e:
            logger.error(f"❌ Error waiting for workflow: {str(e)}")
            raise

    async def send_call_completed_signal(
        self,
        workflow_id: str,
        call_sid: str,
        call_data: Dict[str, Any],
    ) -> None:
        """
        Send call_completed signal to running workflow.

        Reference: Temporal Python SDK - Sending Signals
        https://docs.temporal.io/develop/python/clients#sending-signals

        Signals are used to send data to running workflows.
        This signal is called when a voice call webhook is received.

        Args:
            workflow_id: Workflow execution ID
            call_sid: Call session ID
            call_data: Call completion data

        Raises:
            Exception: If signal fails
        """
        try:
            logger.info(f"📞 Sending call_completed signal: {call_sid}")

            handle = self.client.get_workflow_handle(workflow_id)

            # Send signal to workflow
            await handle.signal(
                ParallelProcessingWorkflow.call_completed,
                args=[call_sid, call_data],
            )

            logger.info(f"✅ Signal sent for call {call_sid}")

        except Exception as e:
            logger.error(f"❌ Failed to send signal: {str(e)}")
            raise

    async def describe_workflow(
        self,
        workflow_id: str,
    ) -> Dict[str, Any]:
        """
        Get workflow execution details.

        Reference: Temporal Python SDK - Querying Workflow State
        https://docs.temporal.io/develop/python/clients#querying-workflow-state

        Args:
            workflow_id: Workflow execution ID

        Returns:
            Dict with workflow details (status, history, etc)

        Raises:
            Exception: If query fails
        """
        try:
            handle = self.client.get_workflow_handle(workflow_id)
            description = await handle.describe()

            logger.info(f"📋 Workflow description: {workflow_id}")
            logger.info(f"   📊 Status: {description.status}")
            logger.info(f"   🕐 Started: {description.start_time}")

            return {
                "id": description.id,
                "status": description.status,
                "start_time": description.start_time,
                "close_time": description.close_time,
                "execution_duration": description.execution_duration,
            }

        except Exception as e:
            logger.error(f"❌ Failed to describe workflow: {str(e)}")
            raise

    async def start_and_wait(
        self,
        chat_id: str,
        tenant_id: str,
        steps: list,
        workflow_id: Optional[str] = None,
        task_queue: str = "parallel-processing",
    ) -> WorkflowOutput:
        """
        Convenience method: start workflow and wait for completion.

        Args:
            chat_id: Conversation identifier
            tenant_id: Tenant identifier
            steps: List of WorkflowStep objects
            workflow_id: Optional custom workflow ID
            task_queue: Task queue name

        Returns:
            WorkflowOutput with results
        """
        # Start workflow
        wf_id = await self.start_orchestration(
            chat_id=chat_id,
            tenant_id=tenant_id,
            steps=steps,
            workflow_id=workflow_id,
            task_queue=task_queue,
        )

        # Wait for completion
        result = await self.wait_for_workflow(wf_id)

        return result


async def create_client(
    namespace: str = None,
    temporal_host: str = None,
    api_key: str = None,
    use_cloud: bool = None,
) -> TemporalClient:
    """
    Create and connect a Temporal client.

    Reads configuration from environment variables with fallback defaults.

    Environment Variables:
        TEMPORAL_NAMESPACE: Temporal namespace (default: "default")
        TEMPORAL_HOST: Temporal server address (default: "localhost:7233")
        TEMPORAL_API_KEY: API key for Temporal Cloud
        TEMPORAL_USE_CLOUD: Set to "true" to connect to Temporal Cloud

    Returns:
        Connected TemporalClient instance

    Example:
        # Local
        client = await create_client()

        # Cloud (using env vars)
        # TEMPORAL_USE_CLOUD=true TEMPORAL_HOST=xxx.tmprl.cloud:7233 ...
        client = await create_client()

        # Cloud (explicit)
        client = await create_client(
            namespace="quickstart-aurjobsai-4.gspbw",
            temporal_host="quickstart-aurjobsai-4.gspbw.tmprl.cloud:7233",
            api_key="your-api-key",
            use_cloud=True,
        )
    """
    namespace = namespace or os.environ.get(
        "TEMPORAL_NAMESPACE", "default"
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

    client = TemporalClient(
        namespace=namespace,
        temporal_host=temporal_host,
        api_key=api_key,
        use_cloud=use_cloud,
    )
    await client.connect()
    return client