"""
orchestrator_api.py

Drop-in HTTP replacement for Azure Durable Functions MainOrchestrator.

Azure endpoint the agent was calling:
    POST http://localhost:7071/api/orchestrators/MainOrchestrator

New endpoint (same payload, same response shape):
    POST http://localhost:8001/api/orchestrators/MainOrchestrator

The agent's bulkCalls.js, bulkEmail.js, bulkScreening.js don't change at all.
Just update the env var:
    DURABLE_FUNCTIONS_URL = http://localhost:8001/api/orchestrators/MainOrchestrator

Place this file at:
    temporal_workflow/orchestrator_api.py

Run alongside your worker:
    python -m uvicorn orchestrator_api:app --host 0.0.0.0 --port 8001 --reload
"""

import sys
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

# Path fix — uvicorn subprocess does not inherit sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from temporalio.client import Client
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Temporal client singleton
# ---------------------------------------------------------------------------
_temporal_client: Optional[Client] = None


# ---------------------------------------------------------------------------
# Pydantic models — match exact shape the agent sends
# ---------------------------------------------------------------------------

class PersonMetadataIn(BaseModel):
    name: str = ""
    email: str = ""
    phone: str = ""


class MetadataIn(BaseModel):
    type: str = "direct_command"
    person: PersonMetadataIn = Field(default_factory=PersonMetadataIn)


class EntityDataIn(BaseModel):
    entity_id: str
    file_name: str = "unknown"
    chunks: str = ""
    metadata: MetadataIn = Field(default_factory=MetadataIn)


class StepParametersIn(BaseModel):
    # Screening
    jd_text: str = ""
    jd_entity_id: Optional[str] = None
    screening_criteria: Optional[str] = None
    # Voice calls
    phone_number: Optional[Any] = None
    call_purpose: str = ""
    context_text: str = ""
    call_type: str = "hiring_screening"
    # Emails
    recipients: Optional[List[Dict[str, Any]]] = None
    subject: str = ""
    body: str = ""
    html: Optional[str] = None
    # Shared
    workflow_run_id: str = ""
    employer_id: str = ""
    total_count: int = 0

    class Config:
        extra = "allow"   # accept any additional fields the agent sends


class StepIn(BaseModel):
    step_id: str = ""
    step_number: int = 0
    function_name: str
    entity_data: List[EntityDataIn] = Field(default_factory=list)
    entity_ids: List[str] = Field(default_factory=list)  # bulkEmail sends entity_ids
    parameters: Optional[StepParametersIn] = None
    params: Optional[Dict[str, Any]] = None              # bulkEmail sends params
    depends_on: List[str] = Field(default_factory=list)


class OrchestratorPayload(BaseModel):
    chat_id: str
    tenant_id: str
    steps: List[StepIn]


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _temporal_client

    use_cloud = os.environ.get("TEMPORAL_USE_CLOUD", "false").lower() == "true"
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")

    if use_cloud:
        # Temporal Cloud: TEMPORAL_HOST already includes port (e.g. xxx.tmprl.cloud:7233)
        host    = os.environ.get("TEMPORAL_HOST", "localhost:7233")
        api_key = os.environ.get("TEMPORAL_API_KEY", "")

        logger.info(f"Connecting to Temporal Cloud at {host} ...")
        _temporal_client = await Client.connect(
            host,
            namespace=namespace,
            api_key=api_key,
            tls=True,
        )
    else:
        # Local: separate host and port
        host = os.environ.get("TEMPORAL_HOST", "localhost")
        port = os.environ.get("TEMPORAL_PORT", "7233")

        logger.info(f"Connecting to Temporal at {host}:{port} ...")
        _temporal_client = await Client.connect(f"{host}:{port}", namespace=namespace)

    logger.info("Temporal client connected. Orchestrator API ready.")
    yield
    logger.info("Orchestrator API shutting down.")


app = FastAPI(
    title="AurJobs AI — Orchestrator API",
    description="Drop-in replacement for Azure Durable Functions MainOrchestrator.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "temporal_connected": _temporal_client is not None,
    }


# ---------------------------------------------------------------------------
# Main orchestrator endpoint
# Matches Azure: POST /api/orchestrators/MainOrchestrator
# ---------------------------------------------------------------------------

@app.post("/api/orchestrators/MainOrchestrator")
async def start_orchestration(payload: OrchestratorPayload) -> JSONResponse:
    """
    Start a Temporal workflow — same interface as Azure Durable Functions.

    Accepts the exact payload that bulkCalls.js / bulkEmail.js / bulkScreening.js send.
    Returns the same response shape so the agent code doesn't change.

    Azure response was:
        { id, statusQueryGetUri, terminatePostUri, ... }

    We return the same shape with Temporal equivalents.
    """
    logger.info(
        f"Orchestration request: chat_id={payload.chat_id} | "
        f"tenant_id={payload.tenant_id} | steps={len(payload.steps)}"
    )

    if _temporal_client is None:
        raise HTTPException(status_code=500, detail="Temporal client not ready")

    # ------------------------------------------------------------------
    # Build Temporal WorkflowInput from the agent's payload
    # ------------------------------------------------------------------
    from temporal_workflow.models import (
        WorkflowInput,
        WorkflowStep,
        EntityData,
        EntityMetadata,
        PersonMetadata,
        StepParameters,
    )

    workflow_steps: List[WorkflowStep] = []

    for step in payload.steps:
        # Merge params/parameters — bulkEmail uses `params`, others use `parameters`
        raw_params: Dict[str, Any] = {}
        if step.params:
            raw_params.update(step.params)
        if step.parameters:
            raw_params.update(step.parameters.dict(exclude_none=True))

        # Build step_id — bulkEmail sends step_number, others send step_id
        step_id = step.step_id or f"step_{step.step_number or len(workflow_steps) + 1}"

        # Build entity_data
        # bulkEmail sends entity_ids (plain strings), others send entity_data objects
        entities: List[EntityData] = []

        for e in step.entity_data:
            entities.append(EntityData(
                entity_id=e.entity_id,
                file_name=e.file_name,
                chunks=e.chunks,
                metadata=EntityMetadata(
                    type=e.metadata.type,
                    person=PersonMetadata(
                        name=e.metadata.person.name,
                        email=e.metadata.person.email,
                        phone=e.metadata.person.phone,
                    ),
                ),
            ))

        # bulkEmail: entity_ids are plain email strings — wrap them as entities
        for email_str in step.entity_ids:
            entities.append(EntityData(
                entity_id=email_str,
                file_name="email_recipient",
                metadata=EntityMetadata(
                    type="email_recipient",
                    person=PersonMetadata(email=email_str),
                ),
            ))

        # Build StepParameters from merged raw_params
        step_params = StepParameters(
            jd_text=raw_params.get("jd_text", ""),
            phone_number=raw_params.get("phone_number") or raw_params.get("phone", ""),
            context_text=raw_params.get("context_text", ""),
            template=raw_params.get("call_type", "generic"),
            subject=raw_params.get("subject", "Update from AurJobs AI"),
            purpose=raw_params.get("call_purpose", ""),
            workflow_run_id=raw_params.get("workflow_run_id", ""),
            other_params={k: v for k, v in raw_params.items() if k not in {
                "jd_text", "phone_number", "phone", "context_text",
                "call_type", "subject", "call_purpose", "workflow_run_id",
            }},
        )

        workflow_steps.append(WorkflowStep(
            step_id=step_id,
            function_name=step.function_name,
            entity_data=entities,
            parameters=step_params,
            depends_on=step.depends_on,
        ))

    workflow_input = WorkflowInput(
        chat_id=payload.chat_id,
        tenant_id=payload.tenant_id,
        steps=workflow_steps,
    )

    # ------------------------------------------------------------------
    # Start Temporal workflow
    # ------------------------------------------------------------------
    workflow_id = f"orchestration-{payload.chat_id}-{uuid4().hex[:8]}"
    task_queue  = os.environ.get("TEMPORAL_TASK_QUEUE", "parallel-processing")

    try:
        from temporal_workflow.workflows import ParallelProcessingWorkflow
        from datetime import timedelta

        handle = await _temporal_client.start_workflow(
            ParallelProcessingWorkflow.orchestrate,
            arg=workflow_input,
            id=workflow_id,
            task_queue=task_queue,
            execution_timeout=timedelta(hours=24),
        )

        logger.info(f"Workflow started: {handle.id}")

        # ------------------------------------------------------------------
        # Return same shape as Azure Durable Functions response
        # so bulkCalls.js / bulkEmail.js / bulkScreening.js work unchanged
        # ------------------------------------------------------------------
        base_url = os.environ.get("API_BASE_URL", "http://localhost:8001")

        return JSONResponse(
            status_code=202,
            content={
                "id":                  handle.id,
                "statusQueryGetUri":   f"{base_url}/api/orchestrators/{handle.id}/status",
                "terminatePostUri":    f"{base_url}/api/orchestrators/{handle.id}/terminate",
                "purgeHistoryDeleteUri": f"{base_url}/api/orchestrators/{handle.id}/purge",
                "workflow_id":         handle.id,
                "chat_id":             payload.chat_id,
                "status":              "Running",
            },
        )

    except Exception as exc:
        logger.error(f"Failed to start workflow: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start orchestration: {str(exc)}",
        )


# ---------------------------------------------------------------------------
# Status endpoint — equivalent to Azure statusQueryGetUri
# ---------------------------------------------------------------------------

@app.get("/api/orchestrators/{workflow_id}/status")
async def get_status(workflow_id: str) -> JSONResponse:
    """
    Query workflow status — equivalent to Azure Durable statusQueryGetUri.

    Returns same shape so agent code reading status_url works unchanged.
    """
    if _temporal_client is None:
        raise HTTPException(status_code=500, detail="Temporal client not ready")

    try:
        handle      = _temporal_client.get_workflow_handle(workflow_id)
        description = await handle.describe()

        # Map Temporal status -> Azure Durable status strings
        status_map = {
            "RUNNING":    "Running",
            "COMPLETED":  "Completed",
            "FAILED":     "Failed",
            "CANCELED":   "Canceled",
            "TERMINATED": "Terminated",
            "TIMED_OUT":  "Failed",
        }
        status_str = status_map.get(str(description.status.name), "Unknown")

        return JSONResponse(
            status_code=200,
            content={
                "instanceId":       workflow_id,
                "runtimeStatus":    status_str,
                "createdTime":      description.start_time.isoformat() if description.start_time else None,
                "lastUpdatedTime":  description.close_time.isoformat() if description.close_time else None,
                "workflow_id":      workflow_id,
            },
        )

    except Exception as exc:
        logger.error(f"Failed to get status for {workflow_id}: {exc}")
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Terminate endpoint — equivalent to Azure terminatePostUri
# ---------------------------------------------------------------------------

@app.post("/api/orchestrators/{workflow_id}/terminate")
async def terminate_workflow(workflow_id: str) -> JSONResponse:
    """Terminate a running workflow."""
    if _temporal_client is None:
        raise HTTPException(status_code=500, detail="Temporal client not ready")

    try:
        handle = _temporal_client.get_workflow_handle(workflow_id)
        await handle.terminate(reason="Terminated via API")
        logger.info(f"Workflow terminated: {workflow_id}")
        return JSONResponse(status_code=202, content={"status": "Terminated"})

    except Exception as exc:
        logger.error(f"Failed to terminate {workflow_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Webhook endpoint — call result from voice server
# (combined here so only one port is needed)
# ---------------------------------------------------------------------------

# @app.post("/webhook/call-result")
@app.post("/api/call_result")    # alias — matches CALL_RESULT_WEBHOOK_URL in voice server config
# @app.post("/api/call-result")    # alias — hyphen variant
async def call_result_webhook(request: Request) -> JSONResponse:
    """
    Receive call completion from voice server and signal Temporal workflow.
    Combined here so the agent only needs to point at one port (8001).
    """
    try:
        data: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    call_sid        = data.get("call_sid")
    chat_id         = data.get("chat_id")
    workflow_run_id = data.get("workflow_run_id")

    if not call_sid:
        raise HTTPException(status_code=400, detail="Missing required field: call_sid")

    # workflow_run_id can be None when the call-status safety-net webhook fires
    # after the main webhook already handled the call. Ignore silently.
    if not workflow_run_id:
        logger.info(f"Ignoring webhook with no workflow_run_id: call_sid={call_sid}")
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "no_workflow_run_id"})

    call_data: Dict[str, Any] = {
        "call_sid":      call_sid,
        "chat_id":       chat_id,
        "call_status":   data.get("call_status", "completed"),
        "transcript":    data.get("transcript", []),
        "call_duration": data.get("call_duration", 0),
        "call_outcome":  data.get("call_outcome", ""),
    }

    if _temporal_client is None:
        raise HTTPException(status_code=500, detail="Temporal client not ready")

    try:
        from temporal_workflow.workflows import ParallelProcessingWorkflow

        handle = _temporal_client.get_workflow_handle(workflow_run_id)
        await handle.signal(
            ParallelProcessingWorkflow.call_completed,
            args=[call_sid, call_data],
        )

        logger.info(f"Signal sent: call_sid={call_sid} -> workflow={workflow_run_id}")
        return JSONResponse(status_code=200, content={"status": "ok", "call_sid": call_sid})

    except Exception as exc:
        logger.error(f"Failed to signal workflow: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))