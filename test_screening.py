#!/usr/bin/env python3
"""
test_screening.py — Test resume screening end to end.

Usage:
    # Test 1: Direct activity test (no Temporal needed)
    python test_screening.py direct

    # Test 2: Full workflow test via Temporal (worker must be running)
    python test_screening.py workflow

    # Test 3: Multiple candidates
    python test_screening.py workflow --multi
"""

import asyncio
import sys
import logging
from pathlib import Path
from uuid import uuid4

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

JOB_DESCRIPTION = """
Senior Python Backend Engineer

We are looking for a Senior Python Backend Engineer to join our AI products team.

Requirements:
- 5+ years Python experience
- Strong knowledge of FastAPI or Django REST Framework
- Experience with PostgreSQL and Redis
- Familiarity with cloud platforms (AWS or Azure)
- Experience with async Python (asyncio, aiohttp)
- Nice to have: experience with AI/ML pipelines, vector databases (Pinecone/Qdrant)

Responsibilities:
- Design and build scalable REST APIs
- Integrate third-party AI services (OpenAI, Azure OpenAI)
- Write unit and integration tests
- Participate in code reviews
"""

CANDIDATE_STRONG = {
    "entity_id":       "resume_strong_001",
    "file_name":       "alice_johnson_resume.pdf",
    "candidate_name":  "Alice Johnson",
    "candidate_email": "alice@example.com",
    "candidate_phone": "+919876543210",
    "resume_text": """
Alice Johnson — Senior Backend Engineer
alice@example.com | +919876543210 | github.com/alicejohnson

EXPERIENCE
-----------
Senior Backend Engineer — TechCorp (2020–Present, 4 years)
  - Built high-throughput REST APIs using FastAPI serving 2M+ requests/day
  - Integrated Azure OpenAI for document processing pipeline
  - Designed async workers using asyncio and aiohttp
  - Managed PostgreSQL (partitioning, indexing) and Redis caching layer

Backend Engineer — StartupXYZ (2018–2020, 2 years)
  - Developed Django REST Framework APIs for e-commerce platform
  - Implemented Celery task queues backed by Redis
  - Migrated legacy MySQL to PostgreSQL

SKILLS
-------
Python, FastAPI, Django, asyncio, PostgreSQL, Redis, Azure, AWS,
Docker, Kubernetes, Qdrant (vector DB), OpenAI API, pytest

EDUCATION
----------
B.Tech Computer Science — IIT Delhi (2018)
""",
}

CANDIDATE_WEAK = {
    "entity_id":       "resume_weak_002",
    "file_name":       "bob_intern_resume.pdf",
    "candidate_name":  "Bob Intern",
    "candidate_email": "bob@example.com",
    "candidate_phone": "+919876543211",
    "resume_text": """
Bob Intern
bob@example.com

EXPERIENCE
-----------
Junior Developer — Small Agency (2023–Present, 1 year)
  - Built simple websites using HTML, CSS, JavaScript
  - Some experience with PHP and WordPress
  - Basic MySQL queries

SKILLS
-------
HTML, CSS, JavaScript, PHP, WordPress, MySQL

EDUCATION
----------
B.Sc IT — Local College (2023)
""",
}

CANDIDATE_MEDIUM = {
    "entity_id":       "resume_medium_003",
    "file_name":       "carol_mid_resume.pdf",
    "candidate_name":  "Carol Mid",
    "candidate_email": "carol@example.com",
    "candidate_phone": "+919876543212",
    "resume_text": """
Carol Mid — Python Developer
carol@example.com

EXPERIENCE
-----------
Python Developer — DataCo (2021–Present, 3 years)
  - Built Flask REST APIs for internal analytics dashboards
  - Used PostgreSQL for data storage
  - Some experience with AWS Lambda (serverless)
  - Wrote scripts for data processing with pandas

SKILLS
-------
Python, Flask, PostgreSQL, AWS, pandas, basic Docker

EDUCATION
----------
B.E Computer Engineering — State University (2021)
""",
}


# ---------------------------------------------------------------------------
# TEST 1: Direct activity test (no Temporal needed)
# ---------------------------------------------------------------------------

async def test_direct():
    """
    Call the activity function directly — bypasses Temporal entirely.
    Useful for quick iteration on the screening logic itself.
    """
    logger.info("=" * 60)
    logger.info("TEST: Direct activity call (no Temporal)")
    logger.info("=" * 60)

    # Import the activity function directly
    from temporal_workflow.activities import resume_screening_activity

    candidates = [CANDIDATE_STRONG, CANDIDATE_MEDIUM, CANDIDATE_WEAK]

    for candidate in candidates:
        logger.info(f"\nScreening: {candidate['candidate_name']}")
        logger.info("-" * 40)

        result = await resume_screening_activity(
            resume_text=candidate["resume_text"],
            job_description=JOB_DESCRIPTION,
            chat_id="test_chat_001",
            tenant_id="test_tenant",
            entity_id=candidate["entity_id"],
            file_name=candidate["file_name"],
            candidate_name=candidate["candidate_name"],
            candidate_email=candidate["candidate_email"],
            candidate_phone=candidate["candidate_phone"],
        )

        _print_screening_result(result)

    logger.info("\nDirect test complete.")


# ---------------------------------------------------------------------------
# TEST 2: Full workflow test (worker must be running)
# ---------------------------------------------------------------------------

async def test_workflow(multi: bool = False):
    """
    Run screening through the full Temporal workflow.
    Worker must be running: python main.py worker
    """
    logger.info("=" * 60)
    logger.info("TEST: Full Temporal workflow")
    logger.info("=" * 60)

    from temporal_workflow.models import (
        WorkflowInput,
        WorkflowStep,
        EntityData,
        EntityMetadata,
        PersonMetadata,
        StepParameters,
    )
    from client import create_client

    # Build entity list
    raw_candidates = [CANDIDATE_STRONG]
    if multi:
        raw_candidates = [CANDIDATE_STRONG, CANDIDATE_MEDIUM, CANDIDATE_WEAK]

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
        for c in raw_candidates
    ]

    screening_step = WorkflowStep(
        step_id="step_1",
        function_name="screen_resumes",
        entity_data=entity_data,
        parameters=StepParameters(jd_text=JOB_DESCRIPTION),
        depends_on=[],
    )

    chat_id = f"test_screen_{uuid4().hex[:8]}"

    workflow_input = WorkflowInput(
        chat_id=chat_id,
        tenant_id="test_tenant",
        steps=[screening_step],
    )

    logger.info(f"Starting workflow | chat_id={chat_id} | candidates={len(entity_data)}")

    client = await create_client()

    try:
        result = await client.start_and_wait(
            chat_id=workflow_input.chat_id,
            tenant_id=workflow_input.tenant_id,
            steps=workflow_input.steps,
        )

        logger.info("\n" + "=" * 60)
        logger.info("WORKFLOW RESULT")
        logger.info("=" * 60)
        logger.info(f"Overall status: {result.status}")

        step_result = result.step_results.get("step_1")
        if step_result and step_result.result:
            screening_results = step_result.result.get("screening_results", [])
            logger.info(f"Candidates screened: {len(screening_results)}")
            logger.info(
                f"Successful: {step_result.result.get('successful', 0)} | "
                f"Failed: {step_result.result.get('failed', 0)}"
            )
            logger.info("")
            for res in screening_results:
                _print_screening_result(res)
        else:
            logger.error(f"Step failed: {step_result}")

    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Result printer
# ---------------------------------------------------------------------------

def _print_screening_result(result: dict) -> None:
    if result.get("status") == "failed":
        logger.error(
            f"FAILED  {result.get('candidate_name', 'Unknown')} — "
            f"{result.get('error', 'unknown error')}"
        )
        return

    score          = result.get("score", 0)
    recommendation = result.get("recommendation", "unknown").upper()
    name           = result.get("candidate_name", "Unknown")
    summary        = result.get("summary", "")
    strengths      = result.get("strengths", [])
    gaps           = result.get("gaps", [])
    skills         = result.get("key_skills_matched", [])
    years          = result.get("years_experience")

    bar_filled = int(score * 20)
    bar = "#" * bar_filled + "-" * (20 - bar_filled)

    logger.info(f"Candidate:      {name}")
    logger.info(f"Score:          [{bar}] {score:.2f}")
    logger.info(f"Recommendation: {recommendation}")
    if years is not None:
        logger.info(f"Experience:     {years} years")
    logger.info(f"Skills matched: {', '.join(skills) if skills else 'none'}")
    logger.info(f"Strengths:      {', '.join(strengths[:3]) if strengths else 'none'}")
    logger.info(f"Gaps:           {', '.join(gaps[:3]) if gaps else 'none'}")
    logger.info(f"Summary:        {summary}")
    logger.info("")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Test resume screening")
    parser.add_argument(
        "mode",
        choices=["direct", "workflow"],
        help="direct = call activity function directly | workflow = run via Temporal",
    )
    parser.add_argument(
        "--multi",
        action="store_true",
        help="(workflow mode only) screen 3 candidates instead of 1",
    )
    args = parser.parse_args()

    if args.mode == "direct":
        asyncio.run(test_direct())
    else:
        asyncio.run(test_workflow(multi=args.multi))


if __name__ == "__main__":
    main()