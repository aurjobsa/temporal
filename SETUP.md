# Setup Guide - Temporal Workflow System

Complete step-by-step guide to set up and run the Temporal workflow system.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation](#installation)
3. [Start Temporal Server](#start-temporal-server)
4. [Verify Installation](#verify-installation)
5. [Run Examples](#run-examples)
6. [Next Steps](#next-steps)

---

## Prerequisites

### System Requirements

- **Python**: 3.8 or higher
- **OS**: Linux, macOS, or Windows
- **RAM**: Minimum 2GB (4GB+ recommended)
- **Docker**: (Optional, recommended for Temporal Server)

### Check Python Version

```bash
python3 --version
# Expected: Python 3.8.0 or higher
```

---

## Installation

### Step 1: Create Virtual Environment

```bash
# Navigate to project directory
cd temporal_workflow

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

**Expected output:**
```
Collecting temporalio>=1.7.0
  Downloading temporalio-...
Collecting python-dotenv>=1.0.0
  ...
Successfully installed temporalio-... python-dotenv-... ...
```

### Step 3: Verify Installation

```bash
python -c "import temporalio; print(temporalio.__version__)"
# Expected: 1.7.0 or higher
```

---

## Start Temporal Server

### Option 1: Docker (Recommended)

**Prerequisites**: Docker installed and running

```bash
# Pull and run Temporal Server
docker run --rm -d \
  --name temporal-server \
  -p 7233:7233 \
  -p 8233:8233 \
  -e TEMPORAL_CLI_ADDRESS=localhost:7233 \
  temporaltech/auto-setup:latest

# Verify it's running
docker ps | grep temporal

# Expected output:
# temporal-server  temporaltech/auto-setup:latest  ...  Up X seconds
```

**Access Web UI**: http://localhost:8233

**Stop Server**:
```bash
docker stop temporal-server
```

### Option 2: Temporal CLI

**Prerequisites**: Temporal CLI installed

```bash
# Install CLI (if not already installed)
# macOS:
brew install temporal

# Linux:
curl -sSf https://temporal.download/cli.sh | sh

# Verify installation
temporal --version
```

**Start Server**:
```bash
temporal server start-dev

# Expected output:
# starting temporal server ...
# Temporal Server started
# UI: http://localhost:8233
# gRPC: localhost:7233
```

**Access Web UI**: http://localhost:8233

---

## Verify Installation

### Test 1: Check Server Connectivity

```bash
# Run the test script
python main.py check-server

# Expected output:
# ✅ Temporal Server is running at localhost:7233
```

### Test 2: Start Worker

**Terminal 1** - Start the worker:

```bash
python main.py worker

# Expected output:
# 🏗️  Starting Temporal Worker
# Namespace: default
# Task Queue: parallel-processing
# Server: localhost:7233
#
# 📋 Registered Workflows:
#    - ParallelProcessingWorkflow
#
# 📊 Registered Activities:
#    - resume_screening_activity
#    ...
#
# ⏳ Worker is running - polling task queue...
#    Press Ctrl+C to stop
```

### Test 3: Run Example (in another terminal)

**Terminal 2** - Run an example:

```bash
# While worker is running in Terminal 1, run:
python main.py example start-and-wait

# Expected output:
# ========================================================================
# EXAMPLE 3: Start Workflow and Wait for Completion
# ========================================================================
# ...
# ✅ Workflow started: orchestration-chat_67890
# 📋 To check status, visit: http://localhost:8233/...
# ...
# ========================================================================
# WORKFLOW COMPLETED
# ========================================================================
# 📊 Status: success
# 🎯 Workflow ID: orchestration-chat_67890
# 📋 Completed Steps: 1
#   ✅ Step step_1: success (screen_resumes)
# 📊 Summary: {...}
```

### Test 4: Check Web UI

Open browser: http://localhost:8233

Should see:
- ✅ Workflow history
- ✅ Completed executions
- ✅ Task queue statistics

---

## Run Examples

### Example 1: Simple Workflow (Screening Only)

```bash
# Terminal 1: Start worker
python main.py worker

# Terminal 2: Run example
python main.py example simple

# Expected: Workflow with single screening step
```

### Example 2: Start and Wait

```bash
# Terminal 1: Start worker
python main.py worker

# Terminal 2: Run example
python main.py example start-and-wait

# Expected: Workflow completes and shows results
```

### Example 3: Voice Calls with Signals

```bash
# Terminal 1: Start worker
python main.py worker

# Terminal 2: Run example
python main.py example voice-calls

# Expected: Workflow waits for signal, then completes
```

### Example 4: Complete Multi-Step Workflow

```bash
# Terminal 1: Start worker
python main.py worker

# Terminal 2: Run example
python main.py example complete

# Expected: Screening → Voice Calls → Emails (sequential with parallel within each step)
```

---

## Troubleshooting

### "Connection refused" Error

**Problem**: Cannot connect to Temporal Server

**Solution**:
```bash
# 1. Check if server is running
docker ps | grep temporal
# or
ps aux | grep "temporal server"

# 2. If not running, start it
docker run --rm -d \
  --name temporal-server \
  -p 7233:7233 \
  -p 8233:8233 \
  temporaltech/auto-setup:latest

# 3. Wait a few seconds for startup
sleep 5

# 4. Test connection
python main.py check-server
```

### "No module named 'temporalio'" Error

**Problem**: Dependencies not installed

**Solution**:
```bash
# 1. Activate virtual environment
source venv/bin/activate  # or venv\Scripts\activate on Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Verify
python -c "import temporalio; print('OK')"
```

### Worker Not Processing Tasks

**Problem**: Worker running but not executing activities

**Solution**:
```bash
# 1. Check task queue name matches
# Worker: task_queue="parallel-processing"
# Client: task_queue="parallel-processing"

# 2. Check worker logs for errors
# Look for error messages in worker terminal

# 3. Restart worker
# Press Ctrl+C to stop, then start again
```

### Timeout Error on Voice Calls

**Problem**: Voice call workflow times out waiting for signal

**Solution**:
```bash
# 1. Verify client.send_call_completed_signal() is being called
# Check your webhook handler code

# 2. Verify workflow_id is passed correctly
# Should match the workflow ID from start_orchestration()

# 3. Test signal manually
python -c "
import asyncio
from client import create_client

async def test():
    client = await create_client()
    await client.send_call_completed_signal(
        workflow_id='orchestration-chat_voice_001',
        call_sid='CALL_SID_12345',
        call_data={
            'call_status': 'completed',
            'transcript': ['Hello'],
            'call_duration': 60
        }
    )
    await client.close()

asyncio.run(test())
"
```

---

## Environment Configuration

### Optional: .env File

Create `.env` file for configuration:

```env
# Temporal Server
TEMPORAL_HOST=localhost
TEMPORAL_PORT=7233
TEMPORAL_NAMESPACE=default

# Task Queue
TASK_QUEUE=parallel-processing

# Logging
LOG_LEVEL=INFO
```

### Optional: Custom Configuration

In `main.py` or `worker/__init__.py`:

```python
import os
from dotenv import load_dotenv

load_dotenv()

TEMPORAL_HOST = os.getenv("TEMPORAL_HOST", "localhost")
TEMPORAL_PORT = int(os.getenv("TEMPORAL_PORT", "7233"))
TEMPORAL_NAMESPACE = os.getenv("TEMPORAL_NAMESPACE", "default")
TASK_QUEUE = os.getenv("TASK_QUEUE", "parallel-processing")
```

---

## Next Steps

1. **Review Documentation**
   - Read `README.md` for complete API reference
   - Study `examples.py` for more examples

2. **Implement Activities**
   - Replace placeholder activities in `activities/__init__.py`
   - Connect to your actual APIs:
     - Resume screening: Call your ML model
     - Voice calls: Integrate Twilio/Vonage
     - Emails: Use SendGrid/AWS SES

3. **Integrate with Your App**
   - Create client wrapper for your FastAPI/Django app
   - Add webhook handlers for voice call completion
   - Implement persistence layer (Supabase, etc)

4. **Deploy to Production**
   - Use Temporal Cloud or self-hosted Temporal Server
   - Configure appropriate retry policies
   - Set up monitoring and alerting
   - Add health checks and graceful shutdown

---

## Quick Reference

```bash
# Start Temporal Server (Docker)
docker run --rm -d \
  --name temporal-server \
  -p 7233:7233 -p 8233:8233 \
  temporaltech/auto-setup:latest

# Start Temporal Server (CLI)
temporal server start-dev

# Activate virtual environment
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate      # Windows

# Install dependencies
pip install -r requirements.txt

# Check server
python main.py check-server

# Start worker
python main.py worker

# Run example
python main.py example start-and-wait

# Web UI
http://localhost:8233
```

---

## Support

- **Documentation**: https://docs.temporal.io/develop/python
- **Python SDK**: https://github.com/temporalio/sdk-python
- **Community**: https://temporal.io/slack
- **Issues**: https://github.com/temporalio/sdk-python/issues

---

## Recommended Reading Order

1. `SETUP.md` (this file) - Installation and verification
2. `README.md` - Architecture and API reference
3. `examples.py` - Working examples
4. `models/__init__.py` - Data structures
5. `activities/__init__.py` - Activity implementations
6. `workflows/__init__.py` - Orchestration logic
7. `worker/__init__.py` - Worker setup
8. `client/__init__.py` - Client API

Enjoy using Temporal! 🚀
