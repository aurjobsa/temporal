"""
Examples - Demonstrating how to use the Temporal workflow system.

Reference: https://docs.temporal.io/develop/python/

This file shows:
1. How to start a worker
2. How to start workflows using the client
3. How to handle webhook signals
4. How to wait for workflow completion
"""

import asyncio
import logging
from datetime import datetime
from uuid import uuid4

from models import (
    WorkflowInput,
    WorkflowStep,
    EntityData,
    EntityMetadata,
    PersonMetadata,
    StepParameters,
)
from client import create_client, TemporalClient
from worker import run_worker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# EXAMPLE 1: Running the Worker
# =============================================================================

async def example_run_worker():
    """
    Example: Start the Temporal worker.

    This should run in a separate terminal/process.
    The worker polls the task queue and executes workflow/activity tasks.

    Reference: Temporal Python SDK - Running a Worker
    https://docs.temporal.io/develop/python/workers#running-a-worker

    Terminal command:
        python -m temporal_workflow.worker

    Or call directly:
        await example_run_worker()
    """
    logger.info("=" * 70)
    logger.info("EXAMPLE 1: Running Temporal Worker")
    logger.info("=" * 70)

    # This will block and continuously poll the task queue
    await run_worker(
        namespace="default",
        task_queue="parallel-processing",
        temporal_host="localhost",
        temporal_port=7233,
    )


# =============================================================================
# EXAMPLE 2: Starting a Simple Workflow
# =============================================================================

async def example_start_workflow():
    """
    Example: Start a screening workflow.

    Shows how to:
    1. Create workflow input with steps
    2. Connect client
    3. Start workflow
    4. Get workflow ID for later reference

    Reference: Temporal Python SDK - Starting Workflows
    https://docs.temporal.io/develop/python/clients#starting-workflows
    """
    logger.info("=" * 70)
    logger.info("EXAMPLE 2: Starting a Screening Workflow")
    logger.info("=" * 70)

    # ========================================================================
    # STEP 1: Create workflow input with screening step
    # ========================================================================

    # Create candidate entities
    candidate_1 = EntityData(
        entity_id="resume_001",
        file_name="john_doe_resume.pdf",
        chunks="Python expert with 10 years experience...",
        metadata=EntityMetadata(
            type="resume",
            person=PersonMetadata(
                name="John Doe",
                email="john@example.com",
                phone="+1234567890",
            ),
        ),
    )

    candidate_2 = EntityData(
        entity_id="resume_002",
        file_name="jane_smith_resume.pdf",
        chunks="Full-stack developer with experience in React and Node.js...",
        metadata=EntityMetadata(
            type="resume",
            person=PersonMetadata(
                name="Jane Smith",
                email="jane@example.com",
                phone="+0987654321",
            ),
        ),
    )

    # Create screening step
    screening_step = WorkflowStep(
        step_id="step_1",
        function_name="screen_resumes",
        entity_data=[candidate_1, candidate_2],
        parameters=StepParameters(
            jd_text="We are looking for a senior Python developer with AWS experience",
        ),
        depends_on=[],
    )

    # Create workflow input with unique chat_id
    unique_chat_id = f"chat_{uuid4().hex[:8]}"
    workflow_input = WorkflowInput(
        chat_id=unique_chat_id,
        tenant_id="tenant_abc",
        steps=[screening_step],
    )

    # ========================================================================
    # STEP 2: Connect client and start workflow
    # ========================================================================

    client = await create_client()

    try:
        # Start workflow (don't wait for completion)
        workflow_id = await client.start_orchestration(
            chat_id=workflow_input.chat_id,
            tenant_id=workflow_input.tenant_id,
            steps=workflow_input.steps,
        )

        logger.info(f"✅ Workflow started: {workflow_id}")
        logger.info(
            f"📋 To check status, visit: http://localhost:8233/namespaces/default/workflows/{workflow_id}"
        )

    finally:
        await client.close()


# =============================================================================
# EXAMPLE 3: Starting and Waiting for Workflow Completion
# =============================================================================

async def example_start_and_wait():
    """
    Example: Start workflow and wait for completion.

    Shows how to:
    1. Start a workflow
    2. Wait for it to complete
    3. Get the final result

    Reference: Temporal Python SDK - Waiting for Workflow Completion
    https://docs.temporal.io/develop/python/clients#waiting-for-workflow-completion
    """
    logger.info("=" * 70)
    logger.info("EXAMPLE 3: Start Workflow and Wait for Completion")
    logger.info("=" * 70)

    # Create workflow input (multiple steps)
    screening_step = WorkflowStep(
        step_id="step_1",
        function_name="screen_resumes",
        entity_data=[
            EntityData(
                entity_id="resume_001",
                file_name="resume1.pdf",
                chunks="Sample resume content",
                metadata=EntityMetadata(
                    person=PersonMetadata(
                        name="John",
                        email="john@example.com",
                    ),
                ),
            ),
        ],
        parameters=StepParameters(jd_text="Senior Python Developer"),
    )

    # Use unique chat_id to allow running example multiple times
    unique_chat_id = f"chat_{uuid4().hex[:8]}"

    workflow_input = WorkflowInput(
        chat_id=unique_chat_id,
        tenant_id="tenant_xyz",
        steps=[screening_step],
    )

    client = await create_client()

    try:
        # Start and wait for completion
        logger.info("🚀 Starting workflow and waiting for completion...")

        result = await client.start_and_wait(
            chat_id=workflow_input.chat_id,
            tenant_id=workflow_input.tenant_id,
            steps=workflow_input.steps,
        )

        # Print results
        logger.info("=" * 70)
        logger.info("WORKFLOW COMPLETED")
        logger.info("=" * 70)
        logger.info(f"📊 Status: {result.status}")
        logger.info(f"🎯 Workflow ID: {result.workflow_run_id}")
        logger.info(f"📋 Completed Steps: {len(result.step_results)}")

        for step_id, step_result in result.step_results.items():
            logger.info(
                f"  ✅ Step {step_id}: {step_result.status} "
                f"({step_result.function})"
            )

        logger.info(f"📊 Summary: {result.summary}")

    finally:
        await client.close()


# =============================================================================
# EXAMPLE 4: Voice Calls Workflow with Signal Handling
# =============================================================================

async def example_voice_calls_workflow():
    """
    Example: Start voice calls workflow and send completion signals.

    Shows how to:
    1. Create voice call step
    2. Start workflow
    3. Simulate webhook by sending call_completed signal

    Reference: Temporal Python SDK - Signals
    https://docs.temporal.io/develop/python/workflows#signals
    """
    logger.info("=" * 70)
    logger.info("EXAMPLE 4: Voice Calls Workflow with Signals")
    logger.info("=" * 70)

    # Create candidate for voice call
    candidate = EntityData(
        entity_id="candidate_001",
        file_name="direct_call",
        metadata=EntityMetadata(
            person=PersonMetadata(
                name="John Doe",
                email="john@example.com",
                phone="+919876543210",
            ),
        ),
    )

    # Create voice call step
    voice_step = WorkflowStep(
        step_id="step_1",
        function_name="trigger_voice_call",
        entity_data=[candidate],
        parameters=StepParameters(
            phone_number="+919876543210",
            context_text="We would like to schedule an interview",
        ),
    )

    # Use unique chat_id to allow running example multiple times
    unique_chat_id = f"chat_voice_{uuid4().hex[:8]}"

    workflow_input = WorkflowInput(
        chat_id=unique_chat_id,
        tenant_id="tenant_xyz",
        steps=[voice_step],
    )

    client = await create_client()

    try:
        # Start workflow
        workflow_id = await client.start_orchestration(
            chat_id=workflow_input.chat_id,
            tenant_id=workflow_input.tenant_id,
            steps=workflow_input.steps,
        )

        logger.info(f"✅ Workflow started: {workflow_id}")
        logger.info("⏳ Workflow is waiting for call completions...")

        # Simulate webhook: after 2 seconds, send call_completed signal
        # In production, this would come from your webhook handler
        await asyncio.sleep(2)

        logger.info("📞 Simulating webhook: Sending call_completed signal...")

        # Simulate call completion data (would come from Twilio/Vonage webhook)
        call_data = {
            "call_status": "completed",
            "call_outcome": "success",
            "transcript": [
                "Hello, how are you?",
                "I'm doing well, thanks for calling",
                "We'd like to schedule an interview",
            ],
            "call_duration": 180,  # 3 minutes
        }

        # Send signal - this will unblock the waiting coroutine in the workflow
        await client.send_call_completed_signal(
            workflow_id=workflow_id,
            call_sid="CALL_SID_12345",
            call_data=call_data,
        )

        logger.info("✅ Signal sent")

        # Now wait for workflow to complete
        logger.info("⏳ Waiting for workflow to process signal and complete...")

        result = await client.wait_for_workflow(workflow_id)

        logger.info("=" * 70)
        logger.info("WORKFLOW COMPLETED")
        logger.info("=" * 70)
        logger.info(f"📊 Status: {result.status}")

    finally:
        await client.close()


# =============================================================================
# EXAMPLE 5: Complete Multi-Step Workflow (Screening → Calls → Emails)
# =============================================================================

async def example_complete_workflow():
    """
    Example: Complete multi-step workflow.

    Shows how to:
    1. Create multiple steps (screening, voice calls, emails)
    2. Set up dependencies
    3. Start workflow
    4. Monitor progress via webhooks/signals

    Reference: Temporal Python SDK - Workflow Design Patterns
    https://docs.temporal.io/develop/python/workflows#workflow-definition
    """
    logger.info("=" * 70)
    logger.info("EXAMPLE 5: Complete Multi-Step Workflow")
    logger.info("=" * 70)

    # ========================================================================
    # STEP 1: Screening
    # ========================================================================

    candidates = [
        EntityData(
            entity_id="resume_001",
            file_name="resume1.pdf",
            chunks="Senior Python developer with 8 years experience...",
            metadata=EntityMetadata(
                person=PersonMetadata(
                    name="Alice Johnson",
                    email="alice@example.com",
                    phone="+919876543210",
                ),
            ),
        ),
        EntityData(
            entity_id="resume_002",
            file_name="resume2.pdf",
            chunks="Full-stack developer with React and Node.js...",
            metadata=EntityMetadata(
                person=PersonMetadata(
                    name="Bob Smith",
                    email="bob@example.com",
                    phone="+919876543211",
                ),
            ),
        ),
    ]

    screening_step = WorkflowStep(
        step_id="step_1",
        function_name="screen_resumes",
        entity_data=candidates,
        parameters=StepParameters(
            jd_text="Senior Developer - Python, Node.js, React",
        ),
        depends_on=[],
    )

    # ========================================================================
    # STEP 2: Voice Calls (depends on screening)
    # ========================================================================

    voice_step = WorkflowStep(
        step_id="step_2",
        function_name="trigger_voice_call",
        entity_data=candidates,
        parameters=StepParameters(
            context_text="Following up on your application",
        ),
        depends_on=["step_1"],  # Depends on screening completion
    )

    # ========================================================================
    # STEP 3: Email (depends on voice calls)
    # ========================================================================

    email_step = WorkflowStep(
        step_id="step_3",
        function_name="send_final_emails_activity",
        entity_data=candidates,
        parameters=StepParameters(
            template="offer",
            subject="Job Offer - Senior Developer Position",
            context_text="We are pleased to offer you...",
        ),
        depends_on=["step_2"],  # Depends on voice calls
    )

    # ========================================================================
    # Create workflow input with all steps
    # ========================================================================

    # Use unique chat_id to allow running example multiple times
    unique_chat_id = f"chat_complete_{uuid4().hex[:8]}"

    workflow_input = WorkflowInput(
        chat_id=unique_chat_id,
        tenant_id="tenant_xyz",
        steps=[screening_step, voice_step, email_step],
    )

    client = await create_client()

    try:
        # Start workflow
        workflow_id = await client.start_orchestration(
            chat_id=workflow_input.chat_id,
            tenant_id=workflow_input.tenant_id,
            steps=workflow_input.steps,
        )

        logger.info(f"✅ Workflow started: {workflow_id}")
        logger.info("📋 Steps:")
        logger.info("  1️⃣  Screening (parallel)")
        logger.info("  2️⃣  Voice Calls (parallel, depends on step 1)")
        logger.info("  3️⃣  Emails (parallel, depends on step 2)")

        logger.info("\n⏳ Waiting for workflow to complete...")
        logger.info(
            "💡 In production, send call_completed signals via webhook handler"
        )

        # Simulate call completions after a delay
        # In production, webhooks would send these signals
        await asyncio.sleep(3)

        for i, call_sid in enumerate([f"CALL_SID_{j}" for j in range(len(candidates))]):
            await client.send_call_completed_signal(
                workflow_id=workflow_id,
                call_sid=call_sid,
                call_data={
                    "call_status": "completed",
                    "transcript": ["Hi", "How are you?", "Let's schedule"],
                    "call_duration": 120,
                },
            )
            await asyncio.sleep(0.5)

        # Wait for completion
        result = await client.wait_for_workflow(workflow_id)

        logger.info("=" * 70)
        logger.info("WORKFLOW COMPLETED")
        logger.info("=" * 70)
        logger.info(f"📊 Status: {result.status}")
        logger.info(f"📋 Steps Completed: {len(result.step_results)}")

        for step_id, step_result in result.step_results.items():
            logger.info(
                f"  ✅ {step_id}: {step_result.status} ({step_result.function})"
            )

    finally:
        await client.close()


# =============================================================================
# EXAMPLE 6: Error Handling and Retries
# =============================================================================

async def example_error_handling():
    """
    Example: Workflow error handling and retries.

    Shows how:
    1. Activities are automatically retried on failure
    2. Temporal handles transient failures
    3. Workflow continues if dependencies are met

    Reference: Temporal Python SDK - Activity Retries
    https://docs.temporal.io/develop/python/activities#retries
    """
    logger.info("=" * 70)
    logger.info("EXAMPLE 6: Error Handling and Retries")
    logger.info("=" * 70)

    logger.info("""
    Temporal automatically handles failures:

    1. ACTIVITY FAILURES:
       - Activities are retried with exponential backoff
       - RetryPolicy: max 3 attempts, backoff coefficient 2.0
       - Initial interval: 1 second, max interval: 60 seconds

    2. WORKFLOW FAILURES:
       - Workflow state is durable
       - On worker restart, workflow resumes from last checkpoint
       - No data loss, exactly-once semantics

    3. STEP DEPENDENCIES:
       - If a dependent step fails, subsequent steps are skipped
       - The workflow captures the failure and continues
       - Final status shows which steps failed

    4. SIGNAL TIMEOUTS:
       - Voice calls wait 3 minutes for webhook signals
       - If timeout, workflow records "timeout" status
       - Workflow completes with partial results
    """)


# =============================================================================
# MAIN - Run Examples
# =============================================================================

async def main():
    """
    Main entry point - run all examples.

    To use these examples:

    Terminal 1 (Worker):
        python -c "import asyncio; from examples import example_run_worker; asyncio.run(example_run_worker())"

    Terminal 2 (Client):
        python -c "import asyncio; from examples import example_start_and_wait; asyncio.run(example_start_and_wait())"

    Or run this file:
        python examples.py
    """
    print("\n" + "=" * 70)
    print("TEMPORAL WORKFLOW EXAMPLES")
    print("=" * 70)
    print("""
    Choose which example to run:

    1. Start Worker:           example_run_worker()
    2. Start Simple Workflow:  example_start_workflow()
    3. Start and Wait:         example_start_and_wait()
    4. Voice Calls:            example_voice_calls_workflow()
    5. Complete Workflow:      example_complete_workflow()
    6. Error Handling:         example_error_handling()

    To run an example in terminal:
        python -c "import asyncio; from examples import example_name; asyncio.run(example_name())"

    RECOMMENDED WORKFLOW:
    1. In Terminal 1: Start worker (example_run_worker)
    2. In Terminal 2: Run example_start_and_wait
    3. Watch progress at http://localhost:8233
    """)

    # For demonstration, run error handling example
    await example_error_handling()


if __name__ == "__main__":
    asyncio.run(main())
