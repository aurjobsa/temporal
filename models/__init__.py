"""
Data models for Temporal workflow
Reference: Temporal Python SDK - Using custom data classes
https://docs.temporal.io/develop/python/workflows#required-workflow-input-and-output
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json


@dataclass
class PersonMetadata:
    """Person metadata extracted from entity data."""
    name: str = ""
    email: str = ""
    phone: str = ""


@dataclass
class EntityMetadata:
    """Metadata associated with an entity (resume, email recipient, etc)."""
    type: str = "direct_command"
    person: PersonMetadata = field(default_factory=PersonMetadata)
    other_fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EntityData:
    """
    Represents a data entity that flows through activities.

    Reference: Temporal Python SDK - Activity Parameters
    https://docs.temporal.io/develop/python/activities#activity-parameters

    Attributes:
        entity_id: Unique identifier for the entity
        file_name: Source file or type
        chunks: Content/data payload
        metadata: Associated metadata (person info, etc)
        context: Additional context information
    """
    entity_id: str
    file_name: str
    chunks: str = ""
    metadata: EntityMetadata = field(default_factory=EntityMetadata)
    context: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class StepParameters:
    """Parameters for a workflow step."""
    jd_text: str = ""  # For screening
    phone_number: str = ""  # For voice calls
    context_text: str = ""  # For calls/emails
    template: str = "generic"  # For emails
    subject: str = "Update from AurJobs AI"  # For emails
    purpose: str = ""  # General purpose
    workflow_run_id: str = ""
    other_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowStep:
    """
    Represents a single step in the orchestration workflow.

    Reference: Temporal Python SDK - Workflow Design Patterns
    https://docs.temporal.io/develop/python/workflows#workflow-definition

    Attributes:
        step_id: Unique step identifier
        function_name: Activity function to call (screen_resumes, trigger_voice_call, etc)
        entity_data: List of entities to process
        parameters: Step-specific parameters
        depends_on: List of step IDs this step depends on
    """
    step_id: str
    function_name: str
    entity_data: List[EntityData] = field(default_factory=list)
    parameters: StepParameters = field(default_factory=StepParameters)
    depends_on: List[str] = field(default_factory=list)


@dataclass
class WorkflowInput:
    """
    Main input to the orchestration workflow.

    Reference: Temporal Python SDK - Workflow Input and Output
    https://docs.temporal.io/develop/python/workflows#required-workflow-input-and-output

    Attributes:
        chat_id: Conversation/session identifier
        tenant_id: Tenant/organization identifier
        steps: List of workflow steps to execute
    """
    chat_id: str
    tenant_id: str
    steps: List[WorkflowStep] = field(default_factory=list)


@dataclass
class ActivityResult:
    """
    Result returned from an activity.

    Reference: Temporal Python SDK - Activity Return Values
    https://docs.temporal.io/develop/python/activities#return-values
    """
    status: str  # "success" or "failed"
    function: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class ScreeningResult(ActivityResult):
    """Result from resume screening activity."""
    entity_id: str = ""
    file_name: str = ""
    score: float = 0.0
    feedback: str = ""


@dataclass
class VoiceCallResult(ActivityResult):
    """Result from voice call activity."""
    call_sid: str = ""
    phone: str = ""
    call_status: str = ""  # completed, busy, no-answer, failed
    transcript: List[str] = field(default_factory=list)
    call_duration: int = 0


@dataclass
class EmailResult(ActivityResult):
    """Result from email sending activity."""
    recipient_email: str = ""
    recipient_name: str = ""
    sent: bool = False


@dataclass
class StepResult:
    """
    Result of executing a workflow step.
    Includes status, function name, and detailed results.
    """
    status: str  # "success" or "failed"
    function: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class WorkflowOutput:
    """
    Output from the orchestration workflow.

    Reference: Temporal Python SDK - Workflow Return Values
    https://docs.temporal.io/develop/python/workflows#return-values
    """
    workflow_run_id: str
    chat_id: str
    status: str  # "success" or "failed"
    step_results: Dict[str, StepResult] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
