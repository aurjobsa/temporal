"""
Temporal Workflow System - Parallel Processing Orchestration

A complete implementation of parallel task orchestration using Temporal,
equivalent to Azure Durable Functions.

Features:
- Parallel resume screening (fan-out/fan-in)
- Parallel voice call initiation and webhook-based completion
- Parallel email sending (fan-out/fan-in)
- Report generation with result aggregation
- Built-in dependency management
- Signal-based external event handling
- Automatic retries with exponential backoff
- Durable execution with exactly-once semantics

Reference: https://docs.temporal.io/develop/python

Usage:
    # 1. Start worker
    python -m temporal_workflow.worker

    # 2. Start workflow via client
    from client import create_client
    from models import WorkflowInput, WorkflowStep

    client = await create_client()
    workflow_id = await client.start_orchestration(
        chat_id="chat_123",
        tenant_id="tenant_abc",
        steps=[...]
    )

    result = await client.wait_for_workflow(workflow_id)
    await client.close()

Components:
- models: Data classes for workflow input/output
- activities: Individual task implementations
- workflows: Main orchestration logic
- worker: Task polling and execution
- client: Workflow management API
"""

__version__ = "1.0.0"
__author__ = "Your Name"

# Export main components for easy import
from .models import (
    WorkflowInput,
    WorkflowStep,
    EntityData,
    WorkflowOutput,
    StepResult,
)
from .client import create_client, TemporalClient
from .worker import TemporalWorker

__all__ = [
    "WorkflowInput",
    "WorkflowStep",
    "EntityData",
    "WorkflowOutput",
    "StepResult",
    "create_client",
    "TemporalClient",
    "TemporalWorker",
]
