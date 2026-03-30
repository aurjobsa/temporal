#!/usr/bin/env python3
"""
test_voice_call.py — Test voice call workflow end to end.

Usage:
    # Single call (first candidate in CANDIDATES list)
    python test_voice_call.py workflow

    # Multiple parallel calls — edit CANDIDATES list below with real numbers
    python test_voice_call.py workflow --multi

    # Direct activity test (no Temporal needed, just voice server)
    python test_voice_call.py direct
"""

import asyncio
import sys
import logging
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CANDIDATES — edit phone numbers here to test real parallel calls
# ---------------------------------------------------------------------------

CANDIDATES = [
    {
        "entity_id":       "candidate_001",
        "file_name":       "direct_call",
        "candidate_name":  "Alice Johnson",
        "candidate_email": "alice@example.com",
        "candidate_phone": "+918887596182",   # <-- real number
        "resume_text":     "Senior Python developer, 6 years, FastAPI, Azure, Qdrant.",
    },
    {
        "entity_id":       "candidate_002",
        "file_name":       "direct_call",
        "candidate_name":  "Bob Smith",
        "candidate_email": "bob@example.com",
        "candidate_phone": "+919721558140",   # <-- real number
        "resume_text":     "Full stack developer, React, Node.js, 4 years experience.",
    },
    # {
    #     "entity_id":       "candidate_003",
    #     "file_name":       "direct_call",
    #     "candidate_name":  "Carol Mehta",
    #     "candidate_email": "carol@example.com",
    #     "candidate_phone": "+919876543212",   # <-- real number
    #     "resume_text":     "Data engineer, Python, Spark, AWS, 3 years experience.",
    # },
]

# Single candidate used when --multi is not passed
CANDIDATE = CANDIDATES[0]

JD_CONTEXT = "We are hiring a Senior Python Backend Engineer with Azure and FastAPI experience."


# ---------------------------------------------------------------------------
# MODE 1: Direct activity test
# ---------------------------------------------------------------------------

async def test_direct():
    """Call trigger_single_voice_interview_activity directly — no Temporal needed."""
    logger.info("=" * 60)
    logger.info("TEST: Direct voice activity call")
    logger.info("=" * 60)

    from temporal_workflow.activities import trigger_single_voice_interview_activity

    c = CANDIDATE
    result = await trigger_single_voice_interview_activity(
        chat_id="test_chat_direct",
        tenant_id="test_tenant",
        entity_data=[{
            "entity_id": c["entity_id"],
            "file_name": c["file_name"],
            "chunks":    c["resume_text"],
            "metadata": {
                "type": "resume",
                "person": {
                    "name":  c["candidate_name"],
                    "email": c["candidate_email"],
                    "phone": c["candidate_phone"],
                },
            },
        }],
        parameters={
            "workflow_run_id": f"test-direct-{uuid4().hex[:8]}",
            "call_purpose":    "pre-screening interview",
            "context_text":    JD_CONTEXT,
            "candidate_name":  c["candidate_name"],
        },
    )

    logger.info("=" * 60)
    logger.info(f"Status:   {result.get('status')}")
    logger.info(f"Call SID: {result.get('call_sid')}")
    logger.info(f"Phone:    {result.get('phone')}")
    if result.get("error"):
        logger.error(f"Error:    {result.get('error')}")


# ---------------------------------------------------------------------------
# MODE 2: Full Temporal workflow test
# ---------------------------------------------------------------------------

async def test_workflow(multi: bool = False):
    """
    Run voice calls through the full Temporal workflow.

    With --multi: all CANDIDATES called simultaneously in parallel.
    The workflow fans out all calls at once, then waits for ALL of them
    to complete via webhook signals.

    Total wait time = duration of the SLOWEST single call, not the sum.
    Each call resolves independently the moment its webhook signal arrives.
    """
    from temporal_workflow.models import (
        WorkflowInput,
        WorkflowStep,
        EntityData,
        EntityMetadata,
        PersonMetadata,
        StepParameters,
    )
    from client import create_client

    candidates = CANDIDATES if multi else [CANDIDATE]

    logger.info("=" * 60)
    logger.info(f"TEST: Parallel voice calls — {len(candidates)} candidate(s)")
    logger.info("=" * 60)
    for c in candidates:
        logger.info(f"  {c['candidate_name']} -> {c['candidate_phone']}")
    logger.info("")

    chat_id         = f"test_voice_{uuid4().hex[:8]}"
    workflow_run_id = f"orchestration-{chat_id}"

    # Build one EntityData per candidate — workflow fans out one call per entity
    entity_data = [
        EntityData(
            entity_id=c["entity_id"],
            file_name=c["file_name"],
            chunks=c["resume_text"],
            metadata=EntityMetadata(
                type="resume",
                person=PersonMetadata(
                    name=c["candidate_name"],
                    email=c["candidate_email"],
                    phone=c["candidate_phone"],
                ),
            ),
        )
        for c in candidates
    ]

    voice_step = WorkflowStep(
        step_id="step_1",
        function_name="trigger_voice_call",
        entity_data=entity_data,
        parameters=StepParameters(
            workflow_run_id=workflow_run_id,
            context_text=JD_CONTEXT,
            purpose="voice_interview",
            other_params={
                "call_purpose": "pre-screening interview",
            },
        ),
        depends_on=[],
    )

    client = await create_client()

    try:
        wf_id = await client.start_orchestration(
            chat_id=chat_id,
            tenant_id="test_tenant",
            steps=[voice_step],
            workflow_id=workflow_run_id,
        )

        logger.info(f"Workflow ID: {wf_id}")
        logger.info(f"All {len(candidates)} calls firing in parallel now...")
        logger.info("Waiting for completions via /webhook/call-result signals...")
        logger.info("(Timeout per call: 3 minutes)")
        logger.info("")

        result = await client.wait_for_workflow(wf_id)

        logger.info("=" * 60)
        logger.info("WORKFLOW COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Overall status: {result.status}")

        step_result = result.step_results.get("step_1")
        if step_result and step_result.result:
            r = step_result.result
            logger.info(f"Initiated: {r.get('calls_initiated', 0)}")
            logger.info(f"Completed: {r.get('calls_completed', 0)}")
            logger.info(f"Failed:    {r.get('calls_failed', 0)}")
            logger.info("")
            for call in r.get("call_details", []):
                _print_call_result(call)
        else:
            logger.error(f"Step error: {step_result.error if step_result else 'unknown'}")

    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Result printer
# ---------------------------------------------------------------------------

def _print_call_result(call: dict) -> None:
    logger.info(f"Call SID:   {call.get('call_sid', 'unknown')}")
    logger.info(f"Status:     {call.get('call_status', 'unknown')}")
    logger.info(f"Duration:   {call.get('call_duration', 0)}s")
    if call.get("call_outcome"):
        logger.info(f"Outcome:    {call.get('call_outcome')}")
    transcript = call.get("transcript", [])
    if transcript:
        logger.info(f"Transcript: ({len(transcript)} lines)")
        for line in transcript[:5]:
            logger.info(f"  - {line}")
        if len(transcript) > 5:
            logger.info(f"  ... {len(transcript) - 5} more lines")
    logger.info("")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Test voice call workflow")
    parser.add_argument(
        "mode",
        choices=["direct", "workflow"],
        help="direct = call activity directly | workflow = run via Temporal",
    )
    parser.add_argument(
        "--multi",
        action="store_true",
        help="Call all candidates in CANDIDATES list in parallel",
    )
    args = parser.parse_args()

    if args.mode == "direct":
        asyncio.run(test_direct())
    else:
        asyncio.run(test_workflow(multi=args.multi))


if __name__ == "__main__":
    main()