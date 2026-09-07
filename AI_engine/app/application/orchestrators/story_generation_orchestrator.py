import json
import logging
import re
import traceback
from datetime import UTC, datetime
from uuid import uuid4

import app.config as config
from app.application.commands.story_commands import GenerateChapterCommand
from app.application.dto.story_dtos import AnalysisResult, Issue, LLMRequest
from app.infrastructure.db.postgres_client import (
    attach_job_chapter,
    create_story_chapter,
    get_job,
    get_recent_chapters_content,
    save_chapter_version,
    update_job,
)
from app.infrastructure.llm.llm_gateway import LLMGateway
from app.infrastructure.redis.redis_client import get_redis
from app.infrastructure.vector_store.pgvector_store import search_memories_vector
from app.pipeline.analyzer import StoryAnalyzer
from app.pipeline.narrative_editor import NarrativeEditor
from app.pipeline.planner import StoryPlanner
from app.pipeline.prompt_builder import PromptBuilder
from app.pipeline.retriever import StoryRetriever

logger = logging.getLogger(__name__)

_MAX_AUTO_CONTINUATIONS = 2
_TRUNCATED_FINISH_REASONS = {"LENGTH", "MAX_TOKENS", "MAX_TOKEN"}
_COMPLETE_FINISH_REASONS = {"STOP", "END_TURN", "COMPLETE", "COMPLETED"}


def _needs_continuation(
    content: str,
    target_word_count: int,
    finish_reason: str | None,
) -> bool:
    reason = (finish_reason or "").strip().upper()
    if reason in _TRUNCATED_FINISH_REASONS:
        return True
    if reason in _COMPLETE_FINISH_REASONS:
        return False
    enough_words = len(content.split()) >= target_word_count * 0.9
    has_complete_ending = bool(re.search(r"""[.!?…]["'”’)\]]*$""", content.rstrip()))
    return not enough_words or not has_complete_ending


def _append_continuation(draft: str, continuation: str) -> str:
    draft, continuation = draft.rstrip(), continuation.strip()
    if not continuation:
        return draft
    if continuation.startswith(draft):
        return continuation
    for size in range(min(len(draft), len(continuation), 1000), 39, -1):
        if draft[-size:] == continuation[:size]:
            continuation = continuation[size:].lstrip()
            break
    return f"{draft}\n\n{continuation}" if continuation else draft


async def publish_redis_stream(job_id: str, event: str, data: dict | str):
    """Publish a real-time event to the Redis Pub/Sub channel for SSE streaming."""
    try:
        redis = get_redis()
        channel = f"ai:job:{job_id}:stream"
        message = json.dumps({"event": event, "data": data}, ensure_ascii=False)
        await redis.publish(channel, message)
        logger.debug("Redis Pub: channel=%s, event=%s", channel, event)
    except Exception as exc:
        logger.error("Failed to publish to Redis stream: %s", exc)


def _analysis_unavailable(exc: Exception) -> AnalysisResult:
    return AnalysisResult(
        passed=False,
        score=0,
        issues=[
            Issue(
                type="ANALYZER_UNAVAILABLE",
                severity="MEDIUM",
                description=f"Continuity analyzer unavailable: {exc}",
                suggested_action="Review continuity manually before approval.",
            )
        ],
        primary_issue_type="ANALYZER_UNAVAILABLE",
        needs_manual_review=True,
    )


class StoryGenerationOrchestrator:
    def __init__(
        self,
        planner: StoryPlanner,
        retriever: StoryRetriever,
        prompt_builder: PromptBuilder,
        gateway: LLMGateway,
        analyzer: StoryAnalyzer,
        narrative_editor: NarrativeEditor,
    ):
        self.planner = planner
        self.retriever = retriever
        self.prompt_builder = prompt_builder
        self.gateway = gateway
        self.analyzer = analyzer
        self.narrative_editor = narrative_editor

    async def _transition_job(
        self,
        job_id: str,
        status: str,
        current_step: str,
        progress: int,
        **updates,
    ):
        job = await update_job(
            job_id=job_id,
            status=status,
            current_step=current_step,
            progress=progress,
            **updates,
        )
        if not job:
            return False
        await publish_redis_stream(job_id, "status", {"status": status, "progress": progress})
        return True

    async def _analyze_or_warn(
        self,
        command: GenerateChapterCommand,
        draft: str,
        plan: dict,
        context: dict,
        attempt: int,
    ) -> AnalysisResult:
        try:
            return await self.analyzer.analyze(
                command.story_id, draft, plan, context, attempt=attempt
            )
        except Exception as exc:
            logger.warning(
                "Analyzer failed for story %s; preserving draft: %s",
                command.story_id,
                exc,
            )
            return _analysis_unavailable(exc)

    async def _complete_draft(
        self,
        command: GenerateChapterCommand,
        plan: dict,
        context: dict,
        system_prompt: str,
        draft: str,
        finish_reason: str | None,
        stream_handler,
    ) -> tuple[str, int, bool]:
        rounds = 0
        target = command.chapter.target_word_count
        character_wiki = command.chapter.model_dump(mode="json").get("character_wiki")
        continuity = {
            key: context.get(key, [])
            for key in (
                "must_preserve_facts",
                "continuity_only",
                "character_state",
                "world_constraints",
            )
        }
        while rounds < _MAX_AUTO_CONTINUATIONS and _needs_continuation(
            draft, target, finish_reason
        ):
            remaining = max(target - len(draft.split()), 200)
            request = LLMRequest(
                model=command.model,
                system_prompt=(
                    f"{system_prompt}\n\n"
                    "Tiếp tục chính chương đang viết. Chỉ trả phần nối tiếp; "
                    "không lặp lại đoạn đã có, không mở đầu lại và phải kết thúc "
                    "trọn câu, trọn cảnh."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"[YÊU CẦU GỐC]\n{command.request}\n\n"
                            f"[KẾ HOẠCH]\n"
                            f"{json.dumps(plan, ensure_ascii=False, default=str)}\n\n"
                            f"[DỮ KIỆN PHẢI GIỮ]\n"
                            f"{json.dumps(continuity, ensure_ascii=False, default=str)}\n\n"
                            f"[GIỌNG NHÂN VẬT]\n"
                            f"{json.dumps(character_wiki, ensure_ascii=False, default=str)}\n\n"
                            f"[PHẦN CUỐI BẢN NHÁP]\n{draft[-6000:]}\n\n"
                            f"Viết tiếp khoảng {remaining} từ và hoàn tất chương tự nhiên."
                        ),
                    }
                ],
                temperature=command.generation_config.temperature,
                max_tokens=command.generation_config.max_output_tokens,
                metadata={
                    "target_word_count": remaining,
                    "continuation_round": rounds + 1,
                    "purpose": "chapter_continuation",
                },
            )
            try:
                response = await self.gateway.generate(
                    command.model, request, stream_handler=stream_handler
                )
            except Exception as exc:
                logger.warning("Automatic continuation failed; preserving draft: %s", exc)
                break
            merged = _append_continuation(draft, response.content)
            if merged == draft:
                break
            draft = merged
            finish_reason = response.finish_reason
            rounds += 1
        return (
            draft,
            rounds,
            _needs_continuation(draft, target, finish_reason),
        )

    async def execute(self, command: GenerateChapterCommand, job_id: str) -> dict:
        logger.info("Orchestrator started job %s for story %s", job_id, command.story_id)
        if not await self._transition_job(
            job_id,
            "PLANNING",
            "PLANNER",
            10,
            started_at=datetime.now(UTC),
        ):
            return {"status": "CANCELLED"}

        try:
            recent_chapters = await get_recent_chapters_content(command.story_id, limit=3)
            query_vector = await self.retriever.gateway.get_embeddings(command.request)
            relevant_memories = await search_memories_vector(
                command.story_id, query_vector, limit=5
            )
            plan = await self.planner.create_plan(command, recent_chapters, relevant_memories)
            logger.info("Planner complete for job %s", job_id)
        except Exception as exc:
            error_msg = f"Error during planning phase: {exc}"
            logger.error("%s\n%s", error_msg, traceback.format_exc())
            await self._fail_job(job_id, error_msg)
            return {"status": "FAILED", "error": error_msg}

        if not await self._transition_job(job_id, "RETRIEVING", "RETRIEVER", 30):
            return {"status": "CANCELLED"}

        try:
            context = await self.retriever.retrieve(command.story_id, command, plan)
            logger.info("Retriever complete for job %s", job_id)
        except Exception as exc:
            error_msg = f"Error during retrieval phase: {exc}"
            logger.error("%s\n%s", error_msg, traceback.format_exc())
            await self._fail_job(job_id, error_msg)
            return {"status": "FAILED", "error": error_msg}

        attempts = 0
        max_attempts = command.generation_config.max_revision_attempts
        chapter_id = str(uuid4())
        try:
            source_thread_id = command.metadata.get("thread_id")
            source_message_index = command.metadata.get("message_index")
            chapter_record = await create_story_chapter(
                story_id=command.story_id,
                chapter_id=chapter_id,
                title=command.chapter.title,
                source_thread_id=source_thread_id,
                source_message_index=(
                    int(source_message_index) if source_message_index is not None else None
                ),
                model_alias=command.model,
            )
            if not await attach_job_chapter(job_id, chapter_id):
                return {"status": "CANCELLED"}
        except Exception as exc:
            error_msg = f"Could not register chapter: {exc}"
            logger.error("%s\n%s", error_msg, traceback.format_exc())
            await self._fail_job(job_id, error_msg)
            return {"status": "FAILED", "error": error_msg}

        next_version_number = 1
        last_analysis = None
        last_content = ""
        last_version_row = None
        last_generation_error = None
        narrative_critique_attempted = False
        narrative_revision_attempted = False

        while attempts <= max_attempts:
            if await self._check_job_cancelled(job_id) == "CANCELLED":
                await publish_redis_stream(
                    job_id,
                    "status",
                    {"status": "CANCELLED", "progress": 100},
                )
                return {"status": "CANCELLED"}

            if not await self._transition_job(
                job_id,
                "BUILDING_PROMPT",
                "PROMPT_BUILDER",
                40,
                attempt=attempts,
            ):
                return {"status": "CANCELLED"}

            system_prompt, user_instruction = await self.prompt_builder.build(
                command=command,
                plan=plan,
                context=context,
                previous_analysis=last_analysis,
            )
            if not await self._transition_job(job_id, "GENERATING", "LLM_WRITER", 50):
                return {"status": "CANCELLED"}

            async def stream_handler(chunk: str):
                await publish_redis_stream(job_id, "token", {"content": chunk})

            request = LLMRequest(
                model=command.model,
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_instruction}],
                temperature=command.generation_config.temperature,
                max_tokens=command.generation_config.max_output_tokens,
                metadata={
                    "target_word_count": command.chapter.target_word_count,
                    "attempt": attempts,
                    "purpose": "chapter_writer",
                },
            )
            try:
                response = await self.gateway.generate(
                    command.model, request, stream_handler=stream_handler
                )
            except Exception as exc:
                last_generation_error = f"Error during generation phase: {exc}"
                logger.error("%s\n%s", last_generation_error, traceback.format_exc())
                if last_version_row:
                    break
                await self._fail_job(job_id, last_generation_error)
                return {"status": "FAILED", "error": last_generation_error}

            raw_draft = response.content
            if not raw_draft or not raw_draft.strip():
                last_generation_error = "Writer returned an empty or unusable draft."
                logger.warning(
                    "%s job=%s attempt=%s",
                    last_generation_error,
                    job_id,
                    attempts,
                )
                attempts += 1
                continue

            raw_metadata = {
                "provider": response.provider,
                "model": response.model,
                "latency_ms": response.latency_ms,
                "usage": response.usage.model_dump(),
                "fallback_from": response.fallback_from,
                "fallback_reason": response.fallback_reason,
                "generation_attempt": attempts,
                "source": command.metadata,
                "continuation_rounds": 0,
                "continuation_incomplete": _needs_continuation(
                    raw_draft,
                    command.chapter.target_word_count,
                    response.finish_reason,
                ),
                "raw_draft": True,
            }
            raw_version_number = next_version_number
            next_version_number += 1
            raw_version_row = await save_chapter_version(
                chapter_id=chapter_id,
                story_id=command.story_id,
                version_number=raw_version_number,
                content=raw_draft,
                status="DRAFT",
                model_alias=command.model,
                prompt_template_version="chapter-writer-v2.0-raw",
                generation_metadata=raw_metadata,
                created_by=command.user_id,
            )
            if not raw_version_row:
                return {"status": "CANCELLED"}
            # From this point onward every optional phase may fail without losing the draft.
            last_content = raw_draft
            last_version_row = raw_version_row
            logger.info("Writer draft saved for job %s, attempt %s", job_id, attempts)

            initial_draft = raw_draft
            raw_draft, continuation_rounds, continuation_incomplete = await self._complete_draft(
                command=command,
                plan=plan,
                context=context,
                system_prompt=system_prompt,
                draft=raw_draft,
                finish_reason=response.finish_reason,
                stream_handler=stream_handler,
            )
            raw_metadata = {
                **raw_metadata,
                "continuation_rounds": continuation_rounds,
                "continuation_incomplete": continuation_incomplete,
            }
            if raw_draft != initial_draft:
                raw_version_number = next_version_number
                next_version_number += 1
                raw_version_row = await save_chapter_version(
                    chapter_id=chapter_id,
                    story_id=command.story_id,
                    version_number=raw_version_number,
                    content=raw_draft,
                    status="DRAFT",
                    model_alias=command.model,
                    prompt_template_version="chapter-writer-v2.0-raw",
                    generation_metadata=raw_metadata,
                    created_by=command.user_id,
                )
                if not raw_version_row:
                    return {"status": "CANCELLED"}
                last_content = raw_draft
                last_version_row = raw_version_row
                logger.info(
                    "Assembled draft saved after %s continuation(s) for job %s",
                    continuation_rounds,
                    job_id,
                )

            if await self._check_job_cancelled(job_id) == "CANCELLED":
                return {"status": "CANCELLED"}

            candidate = raw_draft
            narrative_critique = None
            revision_applied = False
            if config.NARRATIVE_EDITING_ENABLED and not narrative_critique_attempted:
                narrative_critique_attempted = True
                try:
                    narrative_critique = await self.narrative_editor.critique(
                        raw_draft, context, command.chapter.character_wiki
                    )
                    if (
                        not narrative_revision_attempted
                        and self.narrative_editor.has_revisable_issues(narrative_critique)
                    ):
                        narrative_revision_attempted = True
                        candidate, revision_applied = await self.narrative_editor.revise(
                            draft=raw_draft,
                            critique=narrative_critique,
                            context=context,
                            plan=plan,
                            character_wiki=command.chapter.character_wiki,
                            model_alias=command.model,
                        )
                except Exception as exc:
                    logger.warning(
                        "Narrative editing failed for job %s; using raw draft: %s",
                        job_id,
                        exc,
                    )
                    candidate = raw_draft
                    revision_applied = False

            analysis = None
            used_raw_fallback = False
            if command.generation_config.auto_analyze:
                if not await self._transition_job(job_id, "ANALYZING", "STORY_ANALYZER", 80):
                    return {"status": "CANCELLED"}

                analysis = await self._analyze_or_warn(command, candidate, plan, context, attempts)
                if revision_applied and analysis.blocking_issues:
                    raw_analysis = await self._analyze_or_warn(
                        command, raw_draft, plan, context, attempts
                    )
                    if not raw_analysis.blocking_issues:
                        candidate = raw_draft
                        analysis = raw_analysis
                        used_raw_fallback = True
                await publish_redis_stream(job_id, "analysis", analysis.model_dump())

                if await self._check_job_cancelled(job_id) == "CANCELLED":
                    return {"status": "CANCELLED"}

            analysis_result = analysis.model_dump() if analysis else None
            generation_metadata = {
                **raw_metadata,
                "raw_draft": candidate == raw_draft,
                "narrative_editing": {
                    "enabled": config.NARRATIVE_EDITING_ENABLED,
                    "critique_attempted": narrative_critique_attempted,
                    "revision_attempted": narrative_revision_attempted,
                    "revision_applied": revision_applied,
                    "used_raw_fallback": used_raw_fallback,
                    "critique": (narrative_critique.model_dump() if narrative_critique else None),
                },
            }
            is_ready = analysis is None or not analysis.blocking_issues
            version_status = "READY_FOR_REVIEW" if is_ready else "DRAFT"

            if candidate == raw_draft:
                version_number = raw_version_number
                prompt_version = "chapter-writer-v2.0-raw"
            else:
                version_number = next_version_number
                next_version_number += 1
                prompt_version = "chapter-writer-v2.0-revised"

            version_row = await save_chapter_version(
                chapter_id=chapter_id,
                story_id=command.story_id,
                version_number=version_number,
                content=candidate,
                status=version_status,
                model_alias=command.model,
                prompt_template_version=prompt_version,
                generation_metadata=generation_metadata,
                analysis_result=analysis_result,
                created_by=command.user_id,
            )
            if not version_row:
                return {"status": "CANCELLED"}
            last_content = candidate
            last_version_row = version_row
            last_analysis = analysis

            if is_ready:
                result = {
                    "chapter_id": chapter_id,
                    "version_id": str(version_row["id"]),
                    "status": "READY_FOR_REVIEW",
                    "title": chapter_record["title"],
                    "content": candidate,
                    "analysis": analysis_result,
                }
                completed_job = await update_job(
                    job_id=job_id,
                    status="COMPLETED",
                    current_step=None,
                    progress=100,
                    chapter_id=chapter_id,
                    result_payload=result,
                    completed_at=datetime.now(UTC),
                )
                if not completed_job:
                    return {"status": "CANCELLED"}
                await publish_redis_stream(job_id, "completed", result)
                return result

            attempts += 1
            if attempts <= max_attempts:
                issue_type = analysis.primary_issue_type
                if issue_type not in {issue.type for issue in analysis.blocking_issues}:
                    issue_type = analysis.blocking_issues[0].type
                logger.warning(
                    "Retrying writer for blocking issue %s (job=%s, attempt=%s)",
                    issue_type,
                    job_id,
                    attempts,
                )

        if not last_version_row:
            error_msg = last_generation_error or "Writer produced no usable draft."
            await self._fail_job(job_id, error_msg)
            return {"status": "FAILED", "error": error_msg}

        result = {
            "chapter_id": chapter_id,
            "version_id": str(last_version_row["id"]),
            "status": "NEEDS_MANUAL_REVIEW",
            "title": chapter_record["title"],
            "content": last_content,
            "analysis": last_analysis.model_dump() if last_analysis else None,
        }
        completed_job = await update_job(
            job_id=job_id,
            status="NEEDS_MANUAL_REVIEW",
            current_step=None,
            progress=100,
            chapter_id=chapter_id,
            result_payload=result,
            completed_at=datetime.now(UTC),
        )
        if not completed_job:
            return {"status": "CANCELLED"}
        await publish_redis_stream(job_id, "completed", result)
        return result

    async def _fail_job(self, job_id: str, error_message: str):
        await update_job(
            job_id=job_id,
            status="FAILED",
            current_step=None,
            progress=100,
            error_payload={"message": error_message},
            completed_at=datetime.now(UTC),
        )
        await publish_redis_stream(
            job_id,
            "status",
            {"status": "FAILED", "error": error_message},
        )

    async def _check_job_cancelled(self, job_id: str) -> str:
        job = await get_job(job_id)
        return job.get("status") if job else "GENERATING"


def build_orchestrator(gateway: LLMGateway) -> StoryGenerationOrchestrator:
    return StoryGenerationOrchestrator(
        planner=StoryPlanner(gateway),
        retriever=StoryRetriever(gateway),
        prompt_builder=PromptBuilder(),
        gateway=gateway,
        analyzer=StoryAnalyzer(gateway),
        narrative_editor=NarrativeEditor(gateway),
    )
