"""
Orchestration Workflow - Main workflow definition.

Reference: https://docs.temporal.io/develop/python/workflows

Workflows are deterministic orchestration logic that:
- Coordinate activities
- Handle retries and timeouts
- Execute in order or parallel (using asyncio.gather)
- Can wait for signals (external events)
- Cannot perform I/O directly (use activities for that)

Key principles:
1. Workflows must be deterministic (same input = same execution path)
2. Use activities for I/O operations
3. Handle failures gracefully
4. Support long-running operations via signals
5. Can be resumed from any point on failure
"""

import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

# Import models
from temporal_workflow.models import (
    WorkflowInput,
    WorkflowStep,
    EntityData,
    WorkflowOutput,
    StepResult,
)

# Import activities — wrapped because activities use requests/openai (non-deterministic I/O)
# which the Temporal workflow sandbox would otherwise reject.
with workflow.unsafe.imports_passed_through():
    from temporal_workflow.activities import (
        resume_screening_activity,
        trigger_single_voice_interview_activity,
        send_final_emails_activity,
        save_to_supabase,
        notify_frontend_activity,
        run_meta_pipeline_activity,
        save_voice_call_result,
    )

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared retry policy and timeouts
# ---------------------------------------------------------------------------
_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=3,
)
_SHORT_TIMEOUT  = timedelta(minutes=2)
_MEDIUM_TIMEOUT = timedelta(minutes=5)
_LONG_TIMEOUT   = timedelta(minutes=10)
_SIGNAL_TIMEOUT = timedelta(minutes=3)


@workflow.defn
class ParallelProcessingWorkflow:
    """
    Main orchestration workflow - equivalent to Azure Durable Functions orchestrator.

    Reference: https://docs.temporal.io/develop/python/workflows#workflow-definition

    Steps execute sequentially; within each step activities run in parallel
    via asyncio.gather(). Voice-call completion is driven by Temporal signals
    sent from the webhook handler.
    """

    def __init__(self) -> None:
        self.step_results: Dict[str, StepResult] = {}
        self.call_completions: Dict[str, Any] = {}

    # =========================================================================
    # ENTRY POINT
    # =========================================================================

    @workflow.run
    async def orchestrate(self, input_data: WorkflowInput) -> WorkflowOutput:
        """
        Main workflow entry point.

        Args:
            input_data: WorkflowInput containing chat_id, tenant_id, and steps

        Returns:
            WorkflowOutput with execution results for all steps
        """
        workflow_run_id = workflow.info().workflow_id
        chat_id    = input_data.chat_id
        tenant_id  = input_data.tenant_id
        steps      = input_data.steps

        workflow.logger.info("=== ORCHESTRATION WORKFLOW STARTED ===")
        workflow.logger.info(f"Workflow ID: {workflow_run_id}")
        workflow.logger.info(f"Chat ID:     {chat_id}")
        workflow.logger.info(f"Total Steps: {len(steps)}")

        try:
            # Validate dependency graph
            workflow.logger.info("Validating dependencies...")
            self._validate_dependencies(steps)

            # Execute steps in order, respecting depends_on
            for step in steps:
                step_id       = step.step_id
                function_name = step.function_name

                workflow.logger.info(f"Executing step {step_id}: {function_name}")

                if not self._check_step_dependencies(step, self.step_results):
                    workflow.logger.error(f"Dependencies not met for step {step_id}")
                    await self._save_step_to_supabase(
                        chat_id, tenant_id, workflow_run_id,
                        step_id, "failed", function_name,
                        error="Dependency not met",
                    )
                    continue

                if function_name == "screen_resumes":
                    await self._execute_screening_step(
                        step, chat_id, tenant_id, workflow_run_id
                    )
                elif function_name == "trigger_voice_call":
                    await self._execute_voice_calls_step(
                        step, chat_id, tenant_id, workflow_run_id
                    )
                elif function_name in ("send_final_emails_activity", "send_emails"):
                    await self._execute_emails_step(
                        step, chat_id, tenant_id, workflow_run_id
                    )
                elif function_name == "generate_report":
                    await self._execute_report_generation_step(
                        step, chat_id, tenant_id, workflow_run_id
                    )
                else:
                    workflow.logger.warning(f"Unknown function: {function_name}")

            workflow.logger.info("=== ORCHESTRATION WORKFLOW COMPLETED ===")

            return WorkflowOutput(
                workflow_run_id=workflow_run_id,
                chat_id=chat_id,
                status="success",
                step_results=self.step_results,
                summary=self._generate_summary(),
            )

        except Exception as exc:
            workflow.logger.error(f"Workflow failed: {exc}")
            return WorkflowOutput(
                workflow_run_id=workflow_run_id,
                chat_id=chat_id,
                status="failed",
                step_results=self.step_results,
                summary={"error": str(exc)},
            )

    # =========================================================================
    # SIGNAL HANDLER
    # =========================================================================

    @workflow.signal
    async def call_completed(self, call_sid: str, call_data: Dict[str, Any]) -> None:
        """
        Receive call completion data from webhook handler.

        Reference: https://docs.temporal.io/develop/python/workflows#signals
        """
        workflow.logger.info(f"Signal received: call_completed sid={call_sid}")
        self.call_completions[call_sid] = call_data

    # =========================================================================
    # SCREENING STEP - parallel fan-out / fan-in
    # =========================================================================

    async def _execute_screening_step(
        self,
        step: WorkflowStep,
        chat_id: str,
        tenant_id: str,
        workflow_run_id: str,
    ) -> None:
        step_id       = step.step_id
        function_name = "screen_resumes"

        workflow.logger.info(f"PARALLEL SCREENING: {len(step.entity_data)} resumes")

        try:
            await self._notify(
                chat_id, "function_status",
                {"chatId": chat_id, "functionName": "Screening", "status": "started"},
            )

            job_description = step.parameters.jd_text

            # Fan-out: one coroutine per entity
            screening_tasks = [
                workflow.execute_activity(
                    resume_screening_activity,
                    args=[
                        entity.chunks,
                        job_description,
                        chat_id,
                        tenant_id,
                        entity.entity_id,
                        entity.file_name,
                        entity.metadata.person.name,
                        entity.metadata.person.email,
                        entity.metadata.person.phone,
                    ],
                    start_to_close_timeout=_MEDIUM_TIMEOUT,
                    retry_policy=_RETRY_POLICY,
                )
                for entity in step.entity_data
            ]

            workflow.logger.info(f"Fan-out: {len(screening_tasks)} parallel screening tasks")

            # Fan-in
            screening_results = await asyncio.gather(*screening_tasks)

            workflow.logger.info(f"Fan-in: {len(screening_results)} results received")

            successful = sum(1 for r in screening_results if r.get("status") == "success")
            failed     = len(screening_results) - successful

            step_result = StepResult(
                status="success",
                function=function_name,
                result={
                    "screening_results": list(screening_results),
                    "total_screened":    len(screening_results),
                    "successful":        successful,
                    "failed":            failed,
                },
            )
            self.step_results[step_id] = step_result

            await self._save_step_to_supabase(
                chat_id, tenant_id, workflow_run_id,
                step_id, "success", function_name,
                result=step_result.result,
            )

            await self._notify(
                chat_id, "function_status",
                {
                    "chatId":       chat_id,
                    "functionName": "Screening",
                    "status": "completed",
                    "step": "screen_resumes",
                    "summary": {
                        "total":   len(screening_results),
                        "success": successful,
                        "failed":  failed,
                    },
                    "results": list(screening_results),
                },
            )

        except Exception as exc:
            workflow.logger.error(f"Screening step failed: {exc}")
            await self._save_step_failure(
                chat_id, tenant_id, workflow_run_id, step_id, function_name, str(exc)
            )

    # =========================================================================
    # VOICE CALLS STEP - parallel initiation + signal-based completion
    # =========================================================================

    async def _execute_voice_calls_step(
        self,
        step: WorkflowStep,
        chat_id: str,
        tenant_id: str,
        workflow_run_id: str,
    ) -> None:
        step_id       = step.step_id
        function_name = "trigger_voice_call"

        workflow.logger.info(f"PARALLEL VOICE CALLS: {len(step.entity_data)} candidates")

        try:
            await self._notify(
                chat_id, "function_status",
                {"chatId": chat_id, "functionName": "trigger_voice_call", "status": "started"},
            )

            # Phase 1: fan-out - initiate all calls in parallel
            call_initiation_tasks = [
                workflow.execute_activity(
                    trigger_single_voice_interview_activity,
                    args=[
                        chat_id,
                        tenant_id,
                        [
                            {
                                "entity_id": entity.entity_id,
                                "file_name": entity.file_name,
                                "chunks":    entity.chunks,
                                "metadata":  {
                                    "type":   entity.metadata.type,
                                    "person": {
                                        "name":  entity.metadata.person.name,
                                        "email": entity.metadata.person.email,
                                        "phone": entity.metadata.person.phone,
                                    },
                                },
                            }
                        ],
                        {
                            "phone_number":    entity.metadata.person.phone or step.parameters.phone_number,
                            "context_text":    step.parameters.context_text,
                            "call_purpose":    step.parameters.purpose,
                            "workflow_run_id": workflow_run_id,  # voice server echoes this in webhook
                        },
                    ],
                    start_to_close_timeout=_LONG_TIMEOUT,
                    retry_policy=_RETRY_POLICY,
                )
                for entity in step.entity_data
            ]

            workflow.logger.info(f"Fan-out: {len(call_initiation_tasks)} parallel calls")

            call_results = await asyncio.gather(*call_initiation_tasks)

            call_sids = [
                r["call_sid"]
                for r in call_results
                if r.get("status") == "success" and r.get("call_sid")
            ]

            workflow.logger.info(f"Calls initiated, tracking {len(call_sids)} SIDs")

            # ------------------------------------------------------------------
            # Phase 2: wait for ALL call signals in parallel (fan-in)
            #
            # WRONG (old) — sequential for loop:
            #   for call_sid in call_sids:
            #       await workflow.wait_condition(...)   # blocks on each one
            #
            # RIGHT — one coroutine per call, all gathered together.
            # All calls are live simultaneously; whichever finishes first
            # unblocks first. Total wait time = slowest single call,
            # NOT sum of all call durations.
            # ------------------------------------------------------------------

            async def _wait_and_save(call_sid: str) -> Dict[str, Any]:
                """Wait for one call's signal then persist it. Runs in parallel."""
                try:
                    await workflow.wait_condition(
                        lambda sid=call_sid: sid in self.call_completions,
                        timeout=_SIGNAL_TIMEOUT,
                    )
                    call_data = self.call_completions[call_sid]
                    workflow.logger.info(f"Call completed: sid={call_sid}")
                except Exception:
                    call_data = {"call_status": "timeout"}
                    workflow.logger.warning(f"Call timed out: sid={call_sid}")

                # Persist this call's result immediately after it resolves
                await workflow.execute_activity(
                    save_voice_call_result,
                    args=[chat_id, tenant_id, call_sid, call_data],
                    start_to_close_timeout=_SHORT_TIMEOUT,
                    retry_policy=_RETRY_POLICY,
                )

                return {
                    "call_sid":      call_sid,
                    "call_status":   call_data.get("call_status", "unknown"),
                    "transcript":    call_data.get("transcript", []),
                    "call_duration": call_data.get("call_duration", 0),
                    "call_outcome":  call_data.get("call_outcome", ""),
                }

            # Fan-in: all calls waited and saved concurrently
            call_details: List[Dict[str, Any]] = list(
                await asyncio.gather(*[_wait_and_save(sid) for sid in call_sids])
            )

            workflow.logger.info(
                f"All {len(call_details)} calls resolved (parallel fan-in complete)"
            )

            successful_calls = sum(
                1 for c in call_details if c.get("call_status") == "completed"
            )
            failed_calls = len(call_results) - successful_calls

            step_result = StepResult(
                status="success" if failed_calls == 0 else "failed",
                function=function_name,
                result={
                    "calls_initiated": len(call_results),
                    "calls_completed": successful_calls,
                    "calls_failed":    failed_calls,
                    "call_sids":       call_sids,
                    "call_details":    call_details,
                },
            )
            self.step_results[step_id] = step_result

            await self._save_step_to_supabase(
                chat_id, tenant_id, workflow_run_id,
                step_id, step_result.status, function_name,
                result=step_result.result,
            )

            # Run meta pipeline on call results
            await workflow.execute_activity(
                run_meta_pipeline_activity,
                args=["", call_details],
                start_to_close_timeout=_MEDIUM_TIMEOUT,
                retry_policy=_RETRY_POLICY,
            )

            await self._notify(
                chat_id, "function_status",
                {
                    "chatId":      chat_id,
                    "functionName": "trigger_voice_call",
                    "status": "completed" if step_result.status == "success" else "failed",
                    "step": "trigger_voice_call",
                    "summary": {
                        "total":     len(call_results),
                        "completed": successful_calls,
                        "failed":    failed_calls,
                    },
                    "results":     call_details,
                    "call_details": call_details,
                },
            )

        except Exception as exc:
            workflow.logger.error(f"Voice calls step failed: {exc}")
            await self._save_step_failure(
                chat_id, tenant_id, workflow_run_id, step_id, function_name, str(exc)
            )

    # =========================================================================
    # EMAIL STEP - parallel fan-out / fan-in
    # =========================================================================

    async def _execute_emails_step(
        self,
        step: WorkflowStep,
        chat_id: str,
        tenant_id: str,
        workflow_run_id: str,
    ) -> None:
        step_id       = step.step_id
        function_name = "send_final_emails_activity"

        workflow.logger.info(f"PARALLEL EMAIL SEND: {len(step.entity_data)} recipients")

        try:
            await self._notify(
                chat_id, "function_status",
                {"chatId": chat_id, "functionName": "Sending_final_emails", "status": "started"},
            )

            if not step.entity_data:
                workflow.logger.warning("No candidates for email")
                self.step_results[step_id] = StepResult(
                    status="success",
                    function=function_name,
                    result={"emails_sent": 0, "message": "No candidates to email"},
                )
                return

            email_tasks = []
            recipients_list = []

            for entity in step.entity_data:
                candidate_email = entity.metadata.person.email
                candidate_name  = entity.metadata.person.name

                if not candidate_email:
                    workflow.logger.warning(
                        f"Entity {entity.entity_id} has no email, skipping"
                    )
                    continue

                recipients_list.append({"name": candidate_name, "email": candidate_email})

                email_tasks.append(
                    workflow.execute_activity(
                        send_final_emails_activity,
                        args=[
                            chat_id,
                            tenant_id,
                            [
                                {
                                    "entity_id": entity.entity_id,
                                    "file_name": entity.file_name,
                                    "metadata":  {
                                        "type":   entity.metadata.type,
                                        "person": {
                                            "name":  candidate_name,
                                            "email": candidate_email,
                                            "phone": entity.metadata.person.phone,
                                        },
                                    },
                                }
                            ],
                            {
                                "recipient_email": candidate_email,
                                "recipient_name":  candidate_name,
                                "template":        step.parameters.template,
                                "context_text":    step.parameters.context_text,
                                "subject":         step.parameters.subject,
                            },
                        ],
                        start_to_close_timeout=_MEDIUM_TIMEOUT,
                        retry_policy=_RETRY_POLICY,
                    )
                )

            workflow.logger.info(f"Fan-out: {len(email_tasks)} parallel emails")

            email_results = await asyncio.gather(*email_tasks)

            workflow.logger.info(f"Fan-in: {len(email_results)} emails processed")

            successful = sum(1 for r in email_results if r.get("status") == "success")
            failed     = len(email_results) - successful

            step_result = StepResult(
                status="success",
                function=function_name,
                result={
                    "emails_sent":    successful,
                    "emails_failed":  failed,
                    "total_attempts": len(email_results),
                    "recipients":     recipients_list,
                    "details":        list(email_results),
                },
            )
            self.step_results[step_id] = step_result

            await self._save_step_to_supabase(
                chat_id, tenant_id, workflow_run_id,
                step_id, "success", function_name,
                result=step_result.result,
            )

            await self._notify(
                chat_id, "function_status",
                {
                    "chatId":       chat_id,
                    "functionName": "send_final_emails_activity",
                    "status": "completed",
                    "step": "send_final_emails_activity",
                    "summary": {
                        "total":   len(email_results),
                        "success": successful,
                        "failed":  failed,
                    },
                    "results": list(email_results),
                },
            )

        except Exception as exc:
            workflow.logger.error(f"Email step failed: {exc}")
            await self._save_step_failure(
                chat_id, tenant_id, workflow_run_id, step_id, function_name, str(exc)
            )

    # =========================================================================
    # REPORT GENERATION STEP
    # =========================================================================

    async def _execute_report_generation_step(
        self,
        step: WorkflowStep,
        chat_id: str,
        tenant_id: str,
        workflow_run_id: str,
    ) -> None:
        step_id       = step.step_id
        function_name = "generate_report"

        workflow.logger.info("REPORT GENERATION: Aggregating results")

        try:
            await self._notify(
                chat_id, "function_status",
                {"functionName": "generate_report", "status": "started"},
            )

            enriched_entities: List[Any] = list(step.entity_data)

            for dep_id in step.depends_on:
                dep_result = self.step_results.get(dep_id)
                if not dep_result or not dep_result.result:
                    continue
                dep_data = dep_result.result
                if "screening_results" in dep_data:
                    enriched_entities.extend(dep_data["screening_results"])
                if "call_details" in dep_data:
                    enriched_entities.extend(dep_data["call_details"])

            workflow.logger.info(
                f"Report will include {len(enriched_entities)} entities"
            )

            step_result = StepResult(
                status="success",
                function=function_name,
                result={"entities_included": len(enriched_entities)},
            )
            self.step_results[step_id] = step_result

            await self._save_step_to_supabase(
                chat_id, tenant_id, workflow_run_id,
                step_id, "success", function_name,
                result=step_result.result,
            )

        except Exception as exc:
            workflow.logger.error(f"Report generation failed: {exc}")
            await self._save_step_failure(
                chat_id, tenant_id, workflow_run_id, step_id, function_name, str(exc)
            )

    # =========================================================================
    # HELPERS
    # =========================================================================

    def _validate_dependencies(self, steps: List[WorkflowStep]) -> None:
        step_ids = {s.step_id for s in steps}
        for step in steps:
            for dep_id in step.depends_on:
                if dep_id not in step_ids:
                    raise ApplicationError(
                        f"Step '{step.step_id}' depends on unknown step '{dep_id}'"
                    )
        workflow.logger.info("All dependencies valid")

    def _check_step_dependencies(
        self,
        step: WorkflowStep,
        completed_steps: Dict[str, StepResult],
    ) -> bool:
        return all(dep_id in completed_steps for dep_id in step.depends_on)

    async def _save_step_to_supabase(
        self,
        chat_id: str,
        tenant_id: str,
        workflow_run_id: str,
        step_id: str,
        status: str,
        function: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Persist step outcome to Supabase (non-fatal if it fails)."""
        try:
            await workflow.execute_activity(
                save_to_supabase,
                args=[
                    chat_id, tenant_id, workflow_run_id,
                    step_id, status, function, result, error,
                ],
                start_to_close_timeout=_SHORT_TIMEOUT,
                retry_policy=_RETRY_POLICY,
            )
        except Exception as exc:
            workflow.logger.warning(f"save_to_supabase non-fatal error: {exc}")

    async def _notify(
        self,
        chat_id: str,
        event: str,
        data: Dict[str, Any],
    ) -> None:
        """Push real-time update to frontend (non-fatal if it fails)."""
        try:
            await workflow.execute_activity(
                notify_frontend_activity,
                args=[chat_id, event, data],
                start_to_close_timeout=_SHORT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            workflow.logger.warning(f"notify_frontend non-fatal error: {exc}")

    async def _save_step_failure(
        self,
        chat_id: str,
        tenant_id: str,
        workflow_run_id: str,
        step_id: str,
        function_name: str,
        error_msg: str,
    ) -> None:
        self.step_results[step_id] = StepResult(
            status="failed", function=function_name, error=error_msg
        )
        await self._save_step_to_supabase(
            chat_id, tenant_id, workflow_run_id,
            step_id, "failed", function_name,
            error=error_msg,
        )

    def _generate_summary(self) -> Dict[str, Any]:
        successful = sum(
            1 for r in self.step_results.values() if r.status == "success"
        )
        return {
            "total_steps":      len(self.step_results),
            "successful_steps": successful,
            "failed_steps":     len(self.step_results) - successful,
            "steps": {
                sid: {"status": r.status, "function": r.function}
                for sid, r in self.step_results.items()
            },
        }


__all__ = ["ParallelProcessingWorkflow"]