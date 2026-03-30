# Temporal Parallel Processing Workflow

Complete implementation of parallel task orchestration using **Temporal** (equivalent to Azure Durable Functions).

This system coordinates parallel execution of:
- 📄 Resume Screening (fan-out/fan-in)
- 📞 Voice Calls (parallel initiation + webhook-based completion)
- 📧 Email Sending (fan-out/fan-in)
- 📊 Report Generation (aggregating results)

## 📋 Table of Contents

1. [Architecture](#architecture)
2. [Project Structure](#project-structure)
3. [Setup](#setup)
4. [Running the System](#running-the-system)
5. [API Reference](#api-reference)
6. [Examples](#examples)
7. [Workflow Design](#workflow-design)
8. [Signal Handling (Voice Calls)](#signal-handling-voice-calls)
9. [Monitoring](#monitoring)
10. [Troubleshooting](#troubleshooting)

---

## Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    Temporal Server                          │
│  - Persistent workflow state                                │
│  - Task queue management                                    │
│  - Web UI (localhost:8233)                                  │
└────────────┬──────────────────────────┬─────────────────────┘
             │                          │
    ┌────────▼─────────┐      ┌────────▼──────────┐
    │  Worker Process  │      │ Client Process(es) │
    │  - Polls tasks   │      │ - Starts workflows │
    │  - Runs activities       │ - Sends signals    │
    │  - Executes logic│      │ - Waits for result │
    └──────────────────┘      └────────────────────┘
```

### Execution Flow

```
1. Client starts workflow
   │
   ├─► WorkflowInput (chat_id, tenant_id, steps)
   │
2. Temporal Server creates execution
   │
3. Worker polls and receives workflow task
   │
4. Worker executes workflow.orchestrate()
   │
   ├─► Step 1: Screening (parallel activities)
   │   ├─► Activity: resume_screening_activity (per resume)
   │   ├─► Activity: resume_screening_activity (per resume)
   │   └─► All activities run in parallel → results
   │
   ├─► Step 2: Voice Calls (parallel initiation + signals)
   │   ├─► Activity: trigger_single_voice_interview (per call)
   │   ├─► Activity: trigger_single_voice_interview (per call)
   │   ├─► Workflow waits for call_completed signals
   │   ├─► Client sends signals via webhook handler
   │   └─► Results collected
   │
   ├─► Step 3: Emails (parallel activities)
   │   ├─► Activity: send_final_emails_activity (per email)
   │   ├─► All emails sent in parallel
   │   └─► Results collected
   │
5. Workflow completes with WorkflowOutput
   │
6. Client receives result
```

---

## Project Structure

```
temporal_workflow/
├── models/
│   └── __init__.py              # Data models (WorkflowInput, StepResult, etc)
│
├── activities/
│   └── __init__.py              # Activity implementations (screening, calls, emails)
│
├── workflows/
│   └── __init__.py              # Main workflow orchestration logic
│
├── worker/
│   └── __init__.py              # Worker that executes tasks
│
├── client/
│   └── __init__.py              # Client to start/manage workflows
│
├── examples.py                   # Comprehensive examples
├── main.py                       # Entry point
├── requirements.txt              # Python dependencies
└── README.md                     # This file
```

---

## Setup

### Prerequisites

- Python 3.8+
- Temporal Server running (local or cloud)
- Docker (optional, for running Temporal Server)

### 1. Install Python Dependencies

```bash
cd temporal_workflow
pip install -r requirements.txt
```

### 2. Start Temporal Server

#### Option A: Docker (Recommended)

```bash
docker run --rm -d \
  --name temporal-server \
  -p 7233:7233 \
  -p 8233:8233 \
  -e TEMPORAL_CLI_ADDRESS=localhost:7233 \
  temporaltech/auto-setup:latest
```

#### Option B: Temporal CLI

```bash
# Install: https://docs.temporal.io/cli
temporal server start-dev
```

#### Verify Server is Running

```bash
# Should show connection successful
python -c "
import asyncio
from temporalio.client import Client

async def test():
    client = await Client.connect('localhost:7233')
    print('✅ Connected to Temporal Server')
    await client.aclose()

asyncio.run(test())
"
```

---

## Running the System

### Option 1: Using main.py

```bash
# Terminal 1: Start worker
python main.py worker

# Terminal 2: Run example
python main.py example start-and-wait
```

### Option 2: Direct Python

```bash
# Terminal 1: Start worker
python -c "
import asyncio
from worker import run_worker
asyncio.run(run_worker())
"

# Terminal 2: Start workflow
python -c "
import asyncio
from examples import example_start_and_wait
asyncio.run(example_start_and_wait())
"
```

### Option 3: As Python Module

```bash
python -m temporal_workflow.worker

# In another terminal
python -m temporal_workflow.examples
```

---

## API Reference

### Models

#### WorkflowInput

```python
from models import WorkflowInput, WorkflowStep

input_data = WorkflowInput(
    chat_id="chat_12345",           # Conversation identifier
    tenant_id="tenant_abc",          # Tenant identifier
    steps=[...]                      # List of WorkflowStep
)
```

#### WorkflowStep

```python
from models import WorkflowStep, EntityData, StepParameters

step = WorkflowStep(
    step_id="step_1",
    function_name="screen_resumes",  # Activity to execute
    entity_data=[...],               # Entities to process
    parameters=StepParameters(...),  # Step parameters
    depends_on=["step_0"]            # Dependencies
)
```

#### EntityData

```python
from models import EntityData, EntityMetadata, PersonMetadata

entity = EntityData(
    entity_id="resume_001",
    file_name="john_doe.pdf",
    chunks="Resume content...",
    metadata=EntityMetadata(
        person=PersonMetadata(
            name="John Doe",
            email="john@example.com",
            phone="+1234567890"
        )
    )
)
```

### Client API

#### Starting a Workflow

```python
from client import create_client

# Create client
client = await create_client()

# Start workflow
workflow_id = await client.start_orchestration(
    chat_id="chat_123",
    tenant_id="tenant_abc",
    steps=[step1, step2],
    workflow_id="optional_custom_id"  # Auto-generated if not provided
)

# Get result
result = await client.wait_for_workflow(workflow_id)

# Cleanup
await client.close()
```

#### Sending Signals (Voice Calls)

```python
# Send signal when call completes (from webhook handler)
await client.send_call_completed_signal(
    workflow_id=workflow_id,
    call_sid="CALL_SID_123",
    call_data={
        "call_status": "completed",
        "transcript": ["Hello", "How are you?"],
        "call_duration": 180
    }
)
```

#### Convenience Method

```python
# Start and wait for completion
result = await client.start_and_wait(
    chat_id="chat_123",
    tenant_id="tenant_abc",
    steps=[...]
)
```

---

## Examples

### Example 1: Simple Screening

```python
from models import WorkflowStep, EntityData, StepParameters
from client import create_client

# Create entities
entities = [EntityData(...), EntityData(...)]

# Create screening step
step = WorkflowStep(
    step_id="step_1",
    function_name="screen_resumes",
    entity_data=entities,
    parameters=StepParameters(
        jd_text="Senior Python Developer"
    )
)

# Run
client = await create_client()
workflow_id = await client.start_orchestration(
    chat_id="chat_123",
    tenant_id="tenant_abc",
    steps=[step]
)
result = await client.wait_for_workflow(workflow_id)
await client.close()
```

### Example 2: Multi-Step with Dependencies

```python
# Step 1: Screening
screening_step = WorkflowStep(
    step_id="step_1",
    function_name="screen_resumes",
    entity_data=candidates,
    parameters=StepParameters(jd_text="..."),
    depends_on=[]
)

# Step 2: Voice Calls (depends on screening)
voice_step = WorkflowStep(
    step_id="step_2",
    function_name="trigger_voice_call",
    entity_data=candidates,
    parameters=StepParameters(context_text="..."),
    depends_on=["step_1"]  # Only runs after step_1 completes
)

# Step 3: Emails (depends on voice calls)
email_step = WorkflowStep(
    step_id="step_3",
    function_name="send_final_emails_activity",
    entity_data=candidates,
    parameters=StepParameters(subject="..."),
    depends_on=["step_2"]
)

# Run all steps in sequence (with parallel execution within each step)
result = await client.start_and_wait(
    chat_id="chat_123",
    tenant_id="tenant_abc",
    steps=[screening_step, voice_step, email_step]
)
```

### Example 3: Handling Voice Call Signals

```python
# Start workflow with voice calls
workflow_id = await client.start_orchestration(
    chat_id="chat_123",
    tenant_id="tenant_abc",
    steps=[voice_call_step]
)

# In your webhook handler (e.g., Twilio webhook endpoint)
@app.post("/webhooks/call-completed")
async def handle_call_webhook(request):
    data = await request.json()

    # Send signal to workflow
    await client.send_call_completed_signal(
        workflow_id=request.query_params["workflow_id"],
        call_sid=data["call_sid"],
        call_data={
            "call_status": data["status"],
            "transcript": data["transcript"],
            "call_duration": data["duration"]
        }
    )

    return {"status": "ok"}
```

---

## Workflow Design

### Parallel Execution Patterns

#### Pattern 1: Fan-out/Fan-in (Screening & Emails)

```python
# Fan-out: Create task for each entity
tasks = [
    execute_activity(resume_screening, entity_1),
    execute_activity(resume_screening, entity_2),
    execute_activity(resume_screening, entity_3),
]

# Parallel execution (all run concurrently)
results = await asyncio.gather(*tasks)

# Fan-in: Collect results and process
```

#### Pattern 2: Signal-based Completion (Voice Calls)

```python
# Phase 1: Initiate all calls in parallel
call_results = await asyncio.gather(
    execute_activity(initiate_call, entity_1),
    execute_activity(initiate_call, entity_2),
)

# Phase 2: Extract call SIDs and create waiting tasks
waiting_tasks = [
    wait_for_signal(f"call_completed_{call_sid}")
    for call_sid in call_sids
]

# Phase 3: Wait for all signals (with timeout)
completed = await asyncio.wait_for(
    asyncio.gather(*waiting_tasks),
    timeout=180  # 3 minutes
)
```

### Dependency Management

Steps execute **sequentially**, but depend on previous steps:

```python
# Step order:
steps = [
    step1,  # Runs immediately
    step2,  # Waits for step1 (depends_on=["step1"])
    step3,  # Waits for step2 (depends_on=["step2"])
]

# Within each step, activities run in parallel
```

### Error Handling

```python
# Automatic retries
retry_policy = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_attempts=3
)

# Activity execution with retry
result = await execute_activity_with_retry(
    my_activity,
    **kwargs,
    retry_policy=retry_policy
)
```

---

## Signal Handling (Voice Calls)

### Overview

Voice calls are initiated in parallel, but completion is **asynchronous** via webhooks.

### Flow

```
1. Workflow initiates multiple calls → Returns call SIDs
2. Workflow waits for call_completed signals
3. External service (Twilio, etc) triggers webhook
4. Webhook handler sends signal to workflow
5. Workflow receives signal and continues
6. All call signals collected → Workflow completes
```

### Implementation

**Step 1: Webhook Handler** (in your FastAPI/Flask app)

```python
@app.post("/webhooks/call-completed")
async def call_webhook(request):
    data = request.json()
    call_sid = data["call_sid"]

    # Get temporal client
    client = await create_client()

    # Send signal to workflow
    await client.send_call_completed_signal(
        workflow_id=data["workflow_id"],
        call_sid=call_sid,
        call_data={
            "call_status": data["call_status"],
            "transcript": data["transcript"],
            "call_duration": data["call_duration"],
            "call_outcome": data["call_outcome"]
        }
    )

    await client.close()
    return {"status": "ok"}
```

**Step 2: Workflow Signal Handler**

```python
# In ParallelProcessingWorkflow

@workflow.signal
async def call_completed(self, call_sid: str, call_data: Dict[str, Any]) -> None:
    """Receives signal from webhook handler"""
    self.call_completions[call_sid] = call_data
```

**Step 3: Waiting for Signals**

```python
# In workflow, wait for signal with timeout
completion_timeout = timedelta(minutes=3)

try:
    completed_calls = await asyncio.wait_for(
        asyncio.gather(*completion_tasks),
        timeout=completion_timeout.total_seconds()
    )
except asyncio.TimeoutError:
    # Handle timeout (some calls didn't complete)
    pass
```

---

## Monitoring

### Web UI

Access Temporal Web UI at: **http://localhost:8233**

Shows:
- ✅ Running workflows
- 📊 Completed workflows
- 📋 Workflow details & timeline
- 🔍 Activity execution history
- ⚠️ Errors and failures

### Logging

Temporal automatically logs workflow and activity execution:

```
2024-03-19 10:15:23 - temporalio.workflow - INFO - 🎭 === ORCHESTRATION WORKFLOW STARTED ===
2024-03-19 10:15:23 - temporalio.activity - INFO - 🔍 Screening resume: John Doe
2024-03-19 10:15:24 - temporalio.activity - INFO - ✅ Screening completed: John Doe (score: 0.85)
```

### Workflow Status Queries

```python
# Get workflow details
description = await client.describe_workflow(workflow_id)
print(f"Status: {description.status}")
print(f"Started: {description.start_time}")
print(f"Closed: {description.close_time}")
```

---

## Troubleshooting

### "Cannot connect to Temporal Server"

```
Error: Failed to connect to localhost:7233

Solution:
1. Check if Temporal Server is running:
   docker ps | grep temporal

2. If not running, start it:
   docker run --rm -d -p 7233:7233 -p 8233:8233 temporaltech/auto-setup:latest

3. Verify connectivity:
   python -c "import asyncio; from client import create_client; asyncio.run(create_client())"
```

### "Workflow not found"

```
Error: Workflow execution not found

Solution:
1. Check workflow ID is correct
2. Verify in Web UI: http://localhost:8233
3. Check worker is running (polling the queue)
```

### "Activity timeout"

```
Error: Activity did not complete within timeout

Solution:
1. Increase timeout in execute_activity_with_retry()
2. Check activity implementation isn't hanging
3. Review activity logs for errors
```

### "Signal not received"

```
Issue: Voice call workflow waiting for signal but webhook never arrives

Solution:
1. Check webhook URL is correct
2. Verify workflow_id is passed to webhook
3. Test webhook manually:
   curl -X POST http://localhost:8000/webhooks/call-completed \
     -H "Content-Type: application/json" \
     -d '{"call_sid":"TEST", "call_status":"completed", "workflow_id":"wf_123"}'
4. Check client.send_call_completed_signal() in webhook handler
```

### "Worker not processing tasks"

```
Issue: Workflow started but worker doesn't execute it

Solution:
1. Verify worker is running and connected
2. Check task queue name matches:
   - Worker: task_queue="parallel-processing"
   - Client: start_orchestration(..., task_queue="parallel-processing")
3. Check worker logs for errors
4. Restart worker if needed
```

---

## Key Differences from Azure Durable Functions

| Aspect | Azure DF | Temporal |
|--------|----------|----------|
| **Parallel** | `context.task_all()` | `asyncio.gather()` |
| **Activities** | `call_activity()` | `execute_activity()` |
| **Signals** | `wait_for_external_event()` | `@workflow.signal` |
| **Retries** | Built-in | `RetryPolicy` |
| **Timeouts** | `create_timer()` | `asyncio.wait_for()` |
| **Language** | C# | Python |
| **Persistence** | Service Fabric | Customizable |

---

## References

- **Temporal Documentation**: https://docs.temporal.io/develop/python
- **Python SDK**: https://github.com/temporalio/sdk-python
- **Workflow Definition**: https://docs.temporal.io/develop/python/workflows
- **Activities**: https://docs.temporal.io/develop/python/activities
- **Workers**: https://docs.temporal.io/develop/python/workers
- **Signals**: https://docs.temporal.io/develop/python/workflows#signals

---

## Support

For issues or questions:
1. Check Temporal docs: https://docs.temporal.io
2. Review examples.py
3. Check Web UI: http://localhost:8233
4. Review activity/workflow logs
