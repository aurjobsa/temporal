"""
Activities module for Temporal workflow.

Activities implemented:
- resume_screening_activity       : Azure OpenAI resume screening
- trigger_single_voice_interview_activity : Posts to voice server, returns call_sid
- save_voice_call_result          : Persists call completion data
- send_final_emails_activity      : Sends emails (placeholder - wire up your email service)
- save_to_supabase                : Persists step results (placeholder - wire up supabase-py)
- notify_frontend_activity        : Pushes real-time updates (placeholder - wire up socket.io)
- run_meta_pipeline_activity      : Meta pipeline (placeholder)

Environment variables required (.env):
    # Azure OpenAI (for screening)
    AZURE_OPENAI_ENDPOINT    = https://<resource>.openai.azure.com/
    AZURE_OPENAI_API_KEY     = <key>
    AZURE_OPENAI_DEPLOYMENT  = gpt-4o
    AZURE_OPENAI_API_VERSION = 2024-02-01

    # Voice server
    VOICE_SERVER_URL         = http://localhost:8000
"""

import os
import json
import logging
import requests
from typing import Any, Dict, List, Optional
from datetime import datetime

from temporalio import activity
from openai import AsyncAzureOpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# =============================================================================
# AZURE OPENAI CLIENT  (module-level singleton — safe inside activities)
# =============================================================================

_aoai_client: Optional[AsyncAzureOpenAI] = None


def _get_aoai_client() -> AsyncAzureOpenAI:
    global _aoai_client
    if _aoai_client is None:
        _aoai_client = AsyncAzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
    return _aoai_client


# =============================================================================
# SCREENING ACTIVITY
# =============================================================================

_SCREENING_SYSTEM_PROMPT = """You are an expert technical recruiter and resume screener.
Evaluate the candidate's resume against the job description and return a structured JSON assessment.

Return ONLY valid JSON — no markdown, no preamble. Schema:
{
  "score": <float 0.0-1.0>,
  "recommendation": "<shortlist|maybe|reject>",
  "strengths": ["<strength1>", "<strength2>", ...],
  "gaps": ["<gap1>", "<gap2>", ...],
  "summary": "<2-3 sentence overall assessment>",
  "years_experience": <int or null>,
  "key_skills_matched": ["<skill1>", "<skill2>", ...]
}

Scoring guide:
  0.8 - 1.0  => shortlist  (strong match)
  0.5 - 0.79 => maybe      (partial match, worth a call)
  0.0 - 0.49 => reject     (poor match)
"""

_SCREENING_USER_PROMPT = """## Job Description
{job_description}

## Candidate Resume
Name:  {candidate_name}
Email: {candidate_email}

{resume_text}

Evaluate this candidate against the job description and return JSON only."""


@activity.defn
async def resume_screening_activity(
    resume_text: str,
    job_description: str,
    chat_id: str,
    tenant_id: str,
    entity_id: str,
    file_name: str,
    candidate_name: str,
    candidate_email: str,
    candidate_phone: str,
) -> Dict[str, Any]:
    """
    Screen a single resume against a job description using Azure OpenAI.

    Returns:
        {
            "status": "success" | "failed",
            "entity_id", "file_name", "candidate_name",
            "candidate_email", "candidate_phone",
            "score": float,               # 0.0 - 1.0
            "recommendation": str,        # shortlist | maybe | reject
            "strengths": list[str],
            "gaps": list[str],
            "summary": str,
            "years_experience": int | None,
            "key_skills_matched": list[str],
            "screened_at": str,
        }
    """
    activity.logger.info(
        f"Screening: {candidate_name} ({candidate_email}) | entity_id={entity_id}"
    )

    try:
        client = _get_aoai_client()

        user_prompt = _SCREENING_USER_PROMPT.format(
            job_description=job_description.strip(),
            candidate_name=candidate_name,
            candidate_email=candidate_email,
            resume_text=resume_text.strip(),
        )

        response = await client.chat.completions.create(
            model=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
            messages=[
                {"role": "system", "content": _SCREENING_SYSTEM_PROMPT},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=800,
            response_format={"type": "json_object"},
        )

        raw_json   = response.choices[0].message.content.strip()
        assessment = json.loads(raw_json)

        score          = float(assessment.get("score", 0.0))
        recommendation = assessment.get("recommendation", "reject")

        activity.logger.info(
            f"Screening done: {candidate_name} | score={score:.2f} | {recommendation}"
        )

        return {
            "status":             "success",
            "entity_id":          entity_id,
            "file_name":          file_name,
            "candidate_name":     candidate_name,
            "candidate_email":    candidate_email,
            "candidate_phone":    candidate_phone,
            "score":              score,
            "recommendation":     recommendation,
            "strengths":          assessment.get("strengths", []),
            "gaps":               assessment.get("gaps", []),
            "summary":            assessment.get("summary", ""),
            "years_experience":   assessment.get("years_experience"),
            "key_skills_matched": assessment.get("key_skills_matched", []),
            "screened_at":        datetime.utcnow().isoformat(),
        }

    except json.JSONDecodeError as exc:
        activity.logger.error(f"JSON parse error for {candidate_name}: {exc}")
        return {
            "status": "failed", "entity_id": entity_id,
            "file_name": file_name, "candidate_name": candidate_name,
            "error": f"JSON parse error: {exc}",
        }

    except Exception as exc:
        activity.logger.error(f"Screening failed for {candidate_name}: {exc}")
        return {
            "status": "failed", "entity_id": entity_id,
            "file_name": file_name, "candidate_name": candidate_name,
            "error": str(exc),
        }


# =============================================================================
# VOICE CALL ACTIVITIES
# =============================================================================

VOICE_SERVER_URL = os.environ.get("VOICE_SERVER_URL", "http://localhost:8000")


@activity.defn
async def trigger_single_voice_interview_activity(
    chat_id: str,
    tenant_id: str,
    entity_data: List[Dict[str, Any]],
    parameters: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Initiate a single voice call via the voice server.

    Ported from Azure Durable Functions triggerVoiceCallActivity.
    POSTs a unified dynamic payload to VOICE_SERVER_URL/api/call.
    Returns call_sid immediately — completion comes via Temporal signal
    sent by the webhook handler when the call ends.

    Args:
        chat_id:     Conversation identifier
        tenant_id:   Tenant identifier
        entity_data: List with single entity dict (candidate / lead info)
        parameters:  Dict with workflow_run_id, phone_number, call_purpose,
                     context_text, and any optional extra fields

    Returns:
        {
            "status":          "success" | "failed",
            "call_sid":        str,
            "phone":           str,
            "entity_id":       str | None,
            "workflow_run_id": str,
            "initiated_at":    str,
        }
    """
    activity.logger.info("=== TRIGGER VOICE CALL ACTIVITY ===")

    try:
        workflow_run_id = parameters.get("workflow_run_id", "")

        # ------------------------------------------------------------------
        # 1. Resolve phone number
        # ------------------------------------------------------------------
        phone = _resolve_phone(parameters, entity_data)
        if not phone:
            raise ValueError("No phone number found in parameters or entity_data")

        phone = _normalize_phone(phone)
        activity.logger.info(f"Calling: {phone} | workflow_run_id: {workflow_run_id}")

        # ------------------------------------------------------------------
        # 2. Build call_purpose and context_text
        # ------------------------------------------------------------------
        call_purpose = parameters.get("call_purpose", "")
        context_text = parameters.get("context_text", "")

        # Fallback: pull context from entity chunks
        if not context_text and entity_data:
            context_text = entity_data[0].get("chunks", "")

        # Fallback: pull from pdf_content
        if not context_text:
            context_text = parameters.get("pdf_content", "")

        # Fallback: infer purpose if we at least have context
        if not call_purpose and context_text:
            call_purpose = "general conversation"

        activity.logger.info(f"Call purpose: {call_purpose} | Context: {len(context_text)} chars")

        # ------------------------------------------------------------------
        # 3. Build extra_data (personalization fields for DynamicPromptBuilder)
        # ------------------------------------------------------------------
        extra_data = _build_extra_data(parameters, entity_data)
        activity.logger.info(f"Extra data keys: {list(extra_data.keys())}")

        # ------------------------------------------------------------------
        # 4. Build unified payload — matches your existing voice server API
        # ------------------------------------------------------------------
        payload = {
            "phone": phone,
            "workflow_type": "dynamic",
            "workflow_data": {
                "call_purpose":    call_purpose,
                "context_text":    context_text,
                "extra_data":      extra_data,
                "chat_id":         chat_id,
                "workflow_run_id": workflow_run_id,
            },
        }

        # ------------------------------------------------------------------
        # 5. POST to voice server
        #    requests is synchronous but that's fine inside an activity
        # ------------------------------------------------------------------
        activity.logger.info(f"Posting to {VOICE_SERVER_URL}/api/call ...")

        resp = requests.post(
            f"{VOICE_SERVER_URL}/api/call",
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()

        result   = resp.json()
        call_sid = result.get("call_sid")

        activity.logger.info(f"Call initiated: SID={call_sid} | phone={phone}")

        return {
            "status":          "success",
            "call_sid":        call_sid,
            "phone":           phone,
            "entity_id":       entity_data[0].get("entity_id") if entity_data else None,
            "workflow_run_id": workflow_run_id,
            "initiated_at":    datetime.utcnow().isoformat(),
        }

    except requests.exceptions.ConnectionError as exc:
        activity.logger.error(f"Voice server unreachable: {exc}")
        raise   # Temporal will retry

    except requests.exceptions.HTTPError as exc:
        activity.logger.error(f"Voice server HTTP error: {exc}")
        raise   # Temporal will retry

    except requests.exceptions.Timeout:
        activity.logger.error("Voice server request timed out")
        raise   # Temporal will retry

    except ValueError as exc:
        # Bad input — no point retrying
        activity.logger.error(f"Bad input: {exc}")
        return {
            "status":          "failed",
            "error":           str(exc),
            "call_sid":        None,
            "phone":           None,
            "entity_id":       entity_data[0].get("entity_id") if entity_data else None,
            "workflow_run_id": parameters.get("workflow_run_id", ""),
        }

    except Exception as exc:
        activity.logger.error(f"Unexpected error in trigger_voice_call: {exc}")
        raise   # Temporal will retry


@activity.defn
async def save_voice_call_result(
    chat_id: str,
    tenant_id: str,
    call_sid: str,
    call_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Save voice call completion data after the call ends (via signal/webhook).

    Args:
        chat_id:   Conversation identifier
        tenant_id: Tenant identifier
        call_sid:  Call session ID
        call_data: Completion data (transcript, duration, status, etc.)
    """
    activity.logger.info(f"Saving call result: {call_sid}")

    try:
        # TODO: Replace with actual Supabase insert
        # from supabase import create_client
        # sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        # sb.table("call_results").insert({
        #     "chat_id": chat_id, "call_sid": call_sid, **call_data
        # }).execute()

        activity.logger.info(f"Call result saved: {call_sid}")
        return {
            "status":   "success",
            "call_sid": call_sid,
            "saved_at": datetime.utcnow().isoformat(),
        }

    except Exception as exc:
        activity.logger.error(f"Save failed for call {call_sid}: {exc}")
        return {"status": "failed", "error": str(exc)}


# =============================================================================
# EMAIL ACTIVITY
# =============================================================================

@activity.defn
async def send_final_emails_activity(
    chat_id: str,
    tenant_id: str,
    entity_data: List[Dict[str, Any]],
    parameters: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Send email to a single recipient.

    TODO: Replace placeholder with SendGrid / AWS SES / your email service.
    """
    activity.logger.info("Sending email")

    try:
        if not entity_data:
            return {"status": "failed", "error": "No entity data provided"}

        recipient_email = parameters.get("recipient_email", "")
        recipient_name  = parameters.get("recipient_name", "")
        template        = parameters.get("template", "generic")
        subject         = parameters.get("subject", "Update from AurJobs AI")

        if not recipient_email:
            return {"status": "failed", "error": "No recipient email provided"}

        # TODO: Replace with actual email sending
        # import sendgrid
        # ...

        activity.logger.info(f"Email sent to {recipient_name} ({recipient_email})")

        return {
            "status":         "success",
            "recipient":      recipient_email,
            "recipient_name": recipient_name,
            "template":       template,
            "sent_at":        datetime.utcnow().isoformat(),
        }

    except Exception as exc:
        activity.logger.error(f"Email send failed: {exc}")
        return {"status": "failed", "error": str(exc)}


# =============================================================================
# PERSISTENCE ACTIVITIES
# =============================================================================

@activity.defn
async def save_to_supabase(
    chat_id: str,
    tenant_id: str,
    workflow_run_id: str,
    step_id: str,
    status: str,
    function: str,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Persist a workflow step result to Supabase.

    TODO: Replace placeholder with actual supabase-py insert.
    """
    activity.logger.info(
        f"Saving to Supabase: workflow={workflow_run_id} | step={step_id} | status={status}"
    )

    try:
        # TODO: Replace with actual Supabase insert
        # from supabase import create_client
        # sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        # sb.table("workflow_steps").upsert({
        #     "chat_id": chat_id, "tenant_id": tenant_id,
        #     "workflow_run_id": workflow_run_id, "step_id": step_id,
        #     "status": status, "function": function,
        #     "result": result, "error": error,
        # }).execute()

        activity.logger.info(f"Saved to Supabase: {step_id}")
        return {"status": "success"}

    except Exception as exc:
        activity.logger.error(f"Save to Supabase failed: {exc}")
        return {"status": "failed", "error": str(exc)}


@activity.defn
async def notify_frontend_activity(
    chat_id: str,
    event: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Notify frontend via your existing Node.js backend WebSocket layer.

    Ported from Azure notifyFrontend activity — same approach:
    POST to Node.js /api/workflow-update -> Node.js emits via Socket.IO.
    Nothing changes on the Node.js or frontend side.

    Environment variable:
        BACKEND_URL = http://localhost:8000  (your Node.js backend)
    """
    backend_url ="http://localhost:8000"
    endpoint    = f"{backend_url}/api/workflow-update"

    # voice server's main.py WorkflowUpdate model expects:
    # { chat_id, event, data: {...} }
    # sio.emit fires payload.event to room payload.chat_id with payload.data
    payload = {
        "chat_id": chat_id,
        "event":   event,
        "data":    data,
    }

    activity.logger.info(
        f"Notifying frontend: event={event} | chat_id={chat_id} -> {endpoint}"
    )

    try:
        response = requests.post(endpoint, json=payload, timeout=5)
        response.raise_for_status()
        activity.logger.info(f"Frontend notified: {event} | status={response.status_code}")
        return {"status": "success", "event": event, "sent_at": datetime.utcnow().isoformat()}

    except requests.exceptions.ConnectionError:
        # Backend not reachable — log and continue, never fail the workflow
        activity.logger.warning(f"Backend unreachable at {endpoint} — skipping")
        return {"status": "skipped", "reason": "backend_unreachable"}

    except requests.exceptions.HTTPError as exc:
        activity.logger.error(f"Backend returned error: {exc}")
        return {"status": "failed", "error": str(exc)}

    except Exception as exc:
        activity.logger.error(f"Frontend notification failed: {exc}")
        return {"status": "failed", "error": str(exc)}


# =============================================================================
# UTILITY ACTIVITIES
# =============================================================================

@activity.defn
async def run_meta_pipeline_activity(
    user_context: str,
    function_result: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Run meta pipeline on function results.

    TODO: Replace placeholder with your actual meta pipeline logic.
    """
    activity.logger.info("Running meta pipeline")

    try:
        # TODO: Replace with actual meta pipeline
        activity.logger.info("Meta pipeline completed")
        return {"status": "success", "message": "Meta pipeline executed"}

    except Exception as exc:
        activity.logger.error(f"Meta pipeline failed: {exc}")
        return {"status": "failed", "error": str(exc)}


# =============================================================================
# VOICE CALL HELPER FUNCTIONS
# =============================================================================

def _resolve_phone(parameters: Dict[str, Any], entity_data: List[Dict]) -> Optional[str]:
    """Resolve phone number from parameters or entity_data."""
    phone_from_params = parameters.get("phone_number")

    if phone_from_params:
        if isinstance(phone_from_params, list):
            # Prefer +91 number
            for p in phone_from_params:
                if p and isinstance(p, str) and p.startswith("+91"):
                    return p
            first = next((p for p in phone_from_params if p), None)
            return str(first) if first else None
        return str(phone_from_params)

    # Fallback: look in entity_data
    if entity_data:
        entity = entity_data[0]
        phone = (
            entity.get("phone")
            or entity.get("metadata", {}).get("phone")
            or entity.get("metadata", {}).get("person", {}).get("phone")
        )
        if phone:
            return str(phone)

    return None


def _normalize_phone(phone: str) -> str:
    """Ensure phone number has a country code prefix."""
    phone = str(phone).strip()
    if not phone.startswith("+"):
        phone = ("+" if phone.startswith("91") else "+91") + phone
    return phone


def _build_extra_data(parameters: Dict[str, Any], entity_data: List[Dict]) -> Dict[str, Any]:
    """
    Collect structured personalization fields for the voice server's
    DynamicPromptBuilder. Picks well-known optional fields from parameters
    and entity_data metadata.
    """
    extra: Dict[str, Any] = {}

    optional_fields = [
        "candidate_name", "company_name", "lead_name", "lead_company",
        "lead_info", "product_name", "sales_script",
        "job_description", "voice_interview_threshold",
    ]
    for field in optional_fields:
        value = parameters.get(field)
        if value and str(value).strip():
            extra[field] = str(value).strip()

    if entity_data:
        entity   = entity_data[0]
        metadata = entity.get("metadata", {})
        person   = metadata.get("person", {})

        if person.get("name") and "candidate_name" not in extra:
            extra["candidate_name"] = person["name"]
        if person.get("email"):
            extra["contact_email"] = person["email"]
        if entity.get("name") and "lead_name" not in extra:
            extra["lead_name"] = entity["name"]
        if entity.get("company") and "lead_company" not in extra:
            extra["lead_company"] = entity["company"]

    return extra