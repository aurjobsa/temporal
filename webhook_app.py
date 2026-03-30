"""
webhook_app.py

Standalone FastAPI app that receives call completion webhooks from your
voice server and signals the waiting Temporal workflow.

Place this file at:
    temporal_workflow/webhook_app.py

Run it as a separate process (alongside your worker):
    uvicorn webhook_app:app --host 0.0.0.0 --port 8001 --reload

Your voice server must POST to:
    http://localhost:8001/webhook/call-result

with body:
{
    "call_sid":        "CAXXXXXXXXXXXXXXXX",
    "chat_id":         "chat_abc123",
    "workflow_run_id": "orchestration-chat_abc123",
    "call_status":     "completed",
    "transcript":      ["Hello", "Hi", ...],
    "call_duration":   180,
    "call_outcome":    "success"
}
"""

import sys
from pathlib import Path

# Path fix — uvicorn subprocess does not inherit sys.path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from temporalio.client import Client
from dotenv import load_dotenv

from temporal_workflow.workflows import ParallelProcessingWorkflow

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Temporal client singleton
# ---------------------------------------------------------------------------
_temporal_client: Client = None


# ---------------------------------------------------------------------------
# App lifespan — connect Temporal client once at startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _temporal_client

    temporal_host = os.environ.get("TEMPORAL_HOST", "localhost")
    temporal_port = os.environ.get("TEMPORAL_PORT", "7233")
    namespace     = os.environ.get("TEMPORAL_NAMESPACE", "default")

    logger.info(f"Connecting to Temporal at {temporal_host}:{temporal_port} ...")

    _temporal_client = await Client.connect(
        f"{temporal_host}:{temporal_port}",
        namespace=namespace,
    )

    logger.info("Temporal client connected. Webhook app ready.")
    yield

    # Shutdown — nothing to explicitly close for Temporal client
    logger.info("Webhook app shutting down.")


app = FastAPI(
    title="AurJobs AI — Call Result Webhook",
    description="Receives voice call completions and signals Temporal workflows.",
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
# Webhook endpoint
# ---------------------------------------------------------------------------

@app.post("/api/call_result")
async def call_result_webhook(request: Request) -> JSONResponse:
    """
    Receive call completion from voice server and signal Temporal workflow.

    Azure equivalent:
        client.raise_event(instance_id=workflow_run_id,
                           event_name=f"CALL_COMPLETED_{call_sid}",
                           event_data=data)

    Temporal equivalent:
        handle.signal(ParallelProcessingWorkflow.call_completed,
                      call_sid=call_sid, call_data=call_data)
    """
    logger.info("Call result webhook received")

    # ------------------------------------------------------------------
    # 1. Parse body
    # ------------------------------------------------------------------
    try:
        data: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    logger.info(f"Payload: {data}")

    call_sid        = data.get("call_sid")
    chat_id         = data.get("chat_id")
    workflow_run_id = data.get("workflow_run_id")

    if not call_sid or not workflow_run_id:
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: call_sid, workflow_run_id",
        )

    # ------------------------------------------------------------------
    # 2. Build call_data — what the workflow signal handler receives
    # ------------------------------------------------------------------
    call_data: Dict[str, Any] = {
        "call_sid":      call_sid,
        "chat_id":       chat_id,
        "call_status":   data.get("call_status", "completed"),
        "transcript":    data.get("transcript", []),
        "call_duration": data.get("call_duration", 0),
        "call_outcome":  data.get("call_outcome", ""),
    }

    # ------------------------------------------------------------------
    # 3. Send Temporal signal to the waiting workflow
    # ------------------------------------------------------------------
    if _temporal_client is None:
        logger.error("Temporal client not initialized")
        raise HTTPException(status_code=500, detail="Temporal client not ready")

    try:
        logger.info(
            f"Signaling workflow: workflow_id={workflow_run_id} | call_sid={call_sid}"
        )

        handle = _temporal_client.get_workflow_handle(workflow_run_id)

        # await handle.signal(
        #     ParallelProcessingWorkflow.call_completed,
        #     call_sid=call_sid,
        #     call_data=call_data,
        # )

        # FIXED
        await handle.signal(
            ParallelProcessingWorkflow.call_completed,
            args=[call_sid, call_data],
        )
        logger.info(f"Signal sent: call_sid={call_sid}")

        return JSONResponse(
            status_code=200,
            content={"status": "ok", "call_sid": call_sid},
        )

    except Exception as exc:
        logger.error(f"Failed to signal workflow: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to signal workflow: {str(exc)}",
        )