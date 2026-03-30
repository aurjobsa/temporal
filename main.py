#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main entry point for Temporal workflow system.

Reference: https://docs.temporal.io/develop/python

Usage:
    # Start worker (polls task queue)
    python main.py worker

    # Run example
    python main.py example start-and-wait
    python main.py example voice-calls
    python main.py example complete

    # More options
    python main.py --help
"""

import asyncio
import sys
import os
import logging
import argparse
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

# Fix encoding on Windows for emoji support
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# Add parent directory to path so temporal_workflow package can be found
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_banner():
    """Print welcome banner."""
    print("\n" + "=" * 70)
    print("🚀 TEMPORAL WORKFLOW SYSTEM")
    print("=" * 70)
    print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("   Docs: https://docs.temporal.io/develop/python")
    print("=" * 70 + "\n")


async def run_worker(
    namespace: str = "default",
    task_queue: str = "parallel-processing",
    temporal_host: str = "localhost:7233",
    api_key: str = "",
    use_cloud: bool = False,
):
    """
    Run the Temporal worker.

    Reference: https://docs.temporal.io/develop/python/workers
    """
    mode = "☁️  Temporal Cloud" if use_cloud else "🖥️  Local"
    logger.info(f"🏗️  Starting Temporal Worker ({mode})")
    logger.info(f"   Namespace: {namespace}")
    logger.info(f"   Task Queue: {task_queue}")
    logger.info(f"   Server: {temporal_host}")
    logger.info("\n📋 Registered Workflows:")
    logger.info("   - ParallelProcessingWorkflow")
    logger.info("\n📊 Registered Activities:")
    logger.info("   - resume_screening_activity")
    logger.info("   - trigger_single_voice_interview_activity")
    logger.info("   - save_voice_call_result")
    logger.info("   - send_final_emails_activity")
    logger.info("   - save_to_supabase")
    logger.info("   - notify_frontend_activity")
    logger.info("   - run_meta_pipeline_activity")
    logger.info("\n⏳ Worker is running - polling task queue...")
    logger.info("   Press Ctrl+C to stop\n")

    try:
        from worker import run_worker as start_worker
        await start_worker(
            namespace=namespace,
            task_queue=task_queue,
            temporal_host=temporal_host,
            api_key=api_key,
            use_cloud=use_cloud,
        )
    except KeyboardInterrupt:
        logger.info("\n✅ Worker stopped")
        sys.exit(0)


async def run_example(example_name: str):
    """
    Run an example.

    Args:
        example_name: Example name (start-and-wait, voice-calls, complete, etc)
    """
    from examples import (
        example_start_and_wait,
        example_voice_calls_workflow,
        example_complete_workflow,
        example_start_workflow,
        example_error_handling,
    )

    examples = {
        "start-and-wait": example_start_and_wait,
        "simple": example_start_workflow,
        "voice-calls": example_voice_calls_workflow,
        "complete": example_complete_workflow,
        "error-handling": example_error_handling,
    }

    if example_name not in examples:
        logger.error(f"❌ Unknown example: {example_name}")
        logger.info("Available examples:")
        for name in examples.keys():
            logger.info(f"  - {name}")
        sys.exit(1)

    logger.info(f"🚀 Running example: {example_name}\n")

    try:
        await examples[example_name]()
    except Exception as e:
        logger.error(f"❌ Example failed: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


async def check_server(host: str = "localhost:7233", namespace: str = "default",
                       api_key: str = "", use_cloud: bool = False):
    """
    Check if Temporal Server is reachable.

    Reference: https://docs.temporal.io/develop/python/set-up-your-local-python
    """
    target = "Temporal Cloud" if use_cloud else f"Temporal Server at {host}"
    logger.info(f"🔗 Checking connection to {target}...")

    try:
        from temporalio.client import Client

        if use_cloud:
            client = await Client.connect(
                host,
                namespace=namespace,
                api_key=api_key,
                tls=True,
            )
        else:
            client = await Client.connect(host, namespace=namespace)

        logger.info(f"✅ Connected to {target}\n")
        return True

    except Exception as e:
        logger.error(f"❌ Cannot connect to {target}: {str(e)}")
        if not use_cloud:
            logger.info("\n📋 To start Temporal Server:")
            logger.info("   Option 1 (Docker):")
            logger.info("     docker run --rm -d -p 7233:7233 -p 8233:8233 \\")
            logger.info("       temporaltech/auto-setup:latest")
            logger.info("\n   Option 2 (Temporal CLI):")
            logger.info("     temporal server start-dev")
            logger.info("\n   Then try again: python main.py worker")
        else:
            logger.info("\n📋 Check your Temporal Cloud settings:")
            logger.info(f"   Host: {host}")
            logger.info(f"   Namespace: {namespace}")
            logger.info("   API Key: (set via TEMPORAL_API_KEY env var)")
        return False


def main():
    """Main entry point."""
    print_banner()

    parser = argparse.ArgumentParser(
        description="Temporal Workflow System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start worker (polls task queue)
  python main.py worker

  # Run example
  python main.py example start-and-wait
  python main.py example voice-calls
  python main.py example complete

  # Check server
  python main.py check-server

  # Show help
  python main.py --help
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Worker command
    worker_parser = subparsers.add_parser("worker", help="Start the worker")
    worker_parser.add_argument(
        "--namespace",
        default=os.environ.get("TEMPORAL_NAMESPACE", "default"),
        help="Temporal namespace (default: from TEMPORAL_NAMESPACE env or 'default')",
    )
    worker_parser.add_argument(
        "--task-queue",
        default=os.environ.get("TEMPORAL_TASK_QUEUE", "parallel-processing"),
        help="Task queue name (default: parallel-processing)",
    )
    worker_parser.add_argument(
        "--host",
        default=os.environ.get("TEMPORAL_HOST", "localhost:7233"),
        help="Temporal Server host:port (default: from TEMPORAL_HOST env or 'localhost:7233')",
    )
    worker_parser.add_argument(
        "--api-key",
        default=os.environ.get("TEMPORAL_API_KEY", ""),
        help="API key for Temporal Cloud (default: from TEMPORAL_API_KEY env)",
    )
    worker_parser.add_argument(
        "--cloud",
        action="store_true",
        default=os.environ.get("TEMPORAL_USE_CLOUD", "false").lower() == "true",
        help="Connect to Temporal Cloud (default: from TEMPORAL_USE_CLOUD env)",
    )

    # Example command
    example_parser = subparsers.add_parser("example", help="Run an example")
    example_parser.add_argument(
        "name",
        choices=[
            "start-and-wait",
            "simple",
            "voice-calls",
            "complete",
            "error-handling",
        ],
        help="Example to run",
    )

    # Check server command
    subparsers.add_parser("check-server", help="Check Temporal Server")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Run command
    if args.command == "worker":
        # Check server first
        if not asyncio.run(check_server(
            host=args.host,
            namespace=args.namespace,
            api_key=args.api_key,
            use_cloud=args.cloud,
        )):
            sys.exit(1)

        asyncio.run(
            run_worker(
                namespace=args.namespace,
                task_queue=args.task_queue,
                temporal_host=args.host,
                api_key=args.api_key,
                use_cloud=args.cloud,
            )
        )

    elif args.command == "example":
        # Check server first
        if not asyncio.run(check_server()):
            sys.exit(1)

        asyncio.run(run_example(args.name))

    elif args.command == "check-server":
        asyncio.run(check_server())


if __name__ == "__main__":
    main()