import logging
import json
import traceback
from datetime import UTC, datetime
from uuid import uuid4

from app.application.commands.story_commands import GenerateChapterCommand
from app.application.dto.story_dtos import LLMRequest
from app.infrastructure.db.postgres_client import (
    get_job, get_recent_chapters_content, save_chapter_version, update_job
)
from app.infrastructure.redis.redis_client import get_redis
from app.infrastructure.llm.llm_gateway import LLMGateway
from app.infrastructure.vector_store.pgvector_store import search_memories_vector
from app.pipeline.planner import StoryPlanner
from app.pipeline.retriever import StoryRetriever
from app.pipeline.prompt_builder import PromptBuilder
from app.pipeline.analyzer import StoryAnalyzer
from app.pipeline.issue_classifier import classify_primary_issue

logger = logging.getLogger(__name__)


async def publish_redis_stream(job_id: str, event: str, data: dict | str):
    """Publishes a real-time event to the Redis Pub/Sub channel for SSE streaming."""
    try:
        redis = get_redis()
        channel = f"ai:job:{job_id}:stream"
        message = json.dumps({"event": event, "data": data}, ensure_ascii=False)
        await redis.publish(channel, message)
        logger.debug(f"Redis Pub: channel={channel}, event={event}")
    except Exception as e:
        logger.error(f"Failed to publish to Redis stream: {e}")


class StoryGenerationOrchestrator:
    def __init__(
        self,
        planner: StoryPlanner,
        retriever: StoryRetriever,
        prompt_builder: PromptBuilder,
        gateway: LLMGateway,
        analyzer: StoryAnalyzer
    ):
        self.planner = planner
        self.retriever = retriever
        self.prompt_builder = prompt_builder
        self.gateway = gateway
        self.analyzer = analyzer

    async def _transition_job(self, job_id: str, status: str, current_step: str, progress: int, **updates):
        job = await update_job(
            job_id=job_id,
            status=status,
            current_step=current_step,
            progress=progress,
            **updates
        )
        if not job:
            return False
        await publish_redis_stream(job_id, "status", {"status": status, "progress": progress})
        return True

    async def execute(self, command: GenerateChapterCommand, job_id: str) -> dict:
        logger.info(f"Orchestrator started job {job_id} for story {command.story_id}")
        
        # 1. Update status to PLANNING
        if not await self._transition_job(
            job_id, "PLANNING", "PLANNER", 10,
            started_at=datetime.now(UTC)
        ):
            return {"status": "CANCELLED"}

        # Step 1: PLANNER
        try:
            recent_chapters = await get_recent_chapters_content(command.story_id, limit=3)
            query_vector = await self.retriever.gateway.get_embeddings(command.request)
            relevant_memories = await search_memories_vector(command.story_id, query_vector, limit=5)
            
            plan = await self.planner.create_plan(command, recent_chapters, relevant_memories)
            logger.info(f"Planner complete for job {job_id}")
        except Exception as e:
            error_msg = f"Error during planning phase: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            await self._fail_job(job_id, error_msg)
            return {"status": "FAILED", "error": error_msg}

        # 2. Update status to RETRIEVING
        if not await self._transition_job(job_id, "RETRIEVING", "RETRIEVER", 30):
            return {"status": "CANCELLED"}

        # Step 2: RETRIEVER
        try:
            context = await self.retriever.retrieve(command.story_id, command, plan)
            logger.info(f"Retriever complete for job {job_id}")
        except Exception as e:
            error_msg = f"Error during retrieval phase: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            await self._fail_job(job_id, error_msg)
            return {"status": "FAILED", "error": error_msg}

        attempts = 0
        max_attempts = command.generation_config.max_revision_attempts
        last_analysis = None
        draft_content = ""
        chapter_id = str(uuid4())

        while attempts <= max_attempts:
            # Check if job was cancelled
            job_status = await self._check_job_cancelled(job_id)
            if job_status == "CANCELLED":
                logger.info(f"Job {job_id} cancelled.")
                await publish_redis_stream(job_id, "status", {"status": "CANCELLED", "progress": 100})
                return {"status": "CANCELLED"}

            # 3. Update status to BUILDING_PROMPT
            if not await self._transition_job(
                job_id, "BUILDING_PROMPT", "PROMPT_BUILDER", 40,
                attempt=attempts
            ):
                return {"status": "CANCELLED"}

            # Step 3: PROMPT BUILDER
            system_prompt, user_instruct = await self.prompt_builder.build(
                command=command,
                plan=plan,
                context=context,
                previous_analysis=last_analysis
            )

            # 4. Update status to GENERATING
            if not await self._transition_job(job_id, "GENERATING", "LLM_WRITER", 50):
                return {"status": "CANCELLED"}

            # Step 4: GENERATE CHAPTER
            async def stream_handler(chunk: str):
                await publish_redis_stream(job_id, "token", {"content": chunk})

            llm_request = LLMRequest(
                model=command.model,
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_instruct}],
                temperature=command.generation_config.temperature,
                max_tokens=command.generation_config.max_output_tokens,
                metadata={"target_word_count": command.chapter.target_word_count, "attempt": attempts}
            )

            try:
                llm_response = await self.gateway.generate(command.model, llm_request, stream_handler=stream_handler)
                draft_content = llm_response.content
                logger.info(f"Writer complete for job {job_id}, attempt {attempts}")
            except Exception as e:
                error_msg = f"Error during generation phase: {e}"
                logger.error(f"{error_msg}\n{traceback.format_exc()}")
                await self._fail_job(job_id, error_msg)
                return {"status": "FAILED", "error": error_msg}

            if await self._check_job_cancelled(job_id) == "CANCELLED":
                return {"status": "CANCELLED"}

            analysis = None
            analysis_result = None
            if command.generation_config.auto_analyze:
                # 5. Update status to ANALYZING
                if not await self._transition_job(job_id, "ANALYZING", "STORY_ANALYZER", 80):
                    return {"status": "CANCELLED"}

                # Step 5: ANALYZER
                try:
                    analysis = await self.analyzer.analyze(
                        command.story_id, draft_content, plan, context, attempt=attempts
                    )
                    analysis_result = analysis.model_dump()
                    await publish_redis_stream(job_id, "analysis", analysis_result)
                    logger.info(f"Analyzer complete for job {job_id}, score {analysis.score}")
                except Exception as e:
                    error_msg = f"Error during analysis phase: {e}"
                    logger.error(f"{error_msg}\n{traceback.format_exc()}")
                    await self._fail_job(job_id, error_msg)
                    return {"status": "FAILED", "error": error_msg}

                if await self._check_job_cancelled(job_id) == "CANCELLED":
                    return {"status": "CANCELLED"}

            # Save draft
            version_status = "READY_FOR_REVIEW" if analysis is None or analysis.passed else "DRAFT"
            version_row = await save_chapter_version(
                chapter_id=chapter_id,
                version_number=attempts + 1,
                content=draft_content,
                status=version_status,
                model_alias=command.model,
                prompt_template_version="chapter-writer-v1.0",
                generation_metadata={
                    "provider": llm_response.provider,
                    "model": llm_response.model,
                    "latency_ms": llm_response.latency_ms,
                    "usage": llm_response.usage.model_dump()
                },
                analysis_result=analysis_result,
                created_by=command.user_id
            )

            if version_status == "READY_FOR_REVIEW":
                result = {
                    "chapter_id": chapter_id,
                    "version_id": str(version_row["id"]),
                    "status": "READY_FOR_REVIEW",
                    "title": command.chapter.title or "Bản nháp sinh bởi AI",
                    "content": draft_content,
                    "analysis": analysis_result
                }
                await update_job(
                    job_id=job_id,
                    status="COMPLETED",
                    current_step=None,
                    progress=100,
                    chapter_id=chapter_id,
                    result_payload=result,
                    completed_at=datetime.now(UTC)
                )
                await publish_redis_stream(job_id, "completed", result)
                return result

            # Retry: Classify issue and retrieve/plan more
            attempts += 1
            last_analysis = analysis
            
            if attempts <= max_attempts:
                issue_type = classify_primary_issue(analysis)
                if issue_type == "CONTEXT_ISSUE":
                    logger.info(f"Context issue identified, fetching more context...")
                    context = await self.retriever.retrieve_more(command.story_id, analysis.issues)
                elif issue_type == "PLANNER_ISSUE":
                    logger.info(f"Planning issue identified, revising plan...")
                    plan = await self.planner.revise_plan(plan, analysis.issues)
                else:
                    logger.info(f"Writing issue identified, rewriting draft...")

        # Revision threshold exceeded
        result = {
            "chapter_id": chapter_id,
            "version_id": str(version_row["id"]),
            "status": "NEEDS_MANUAL_REVIEW",
            "title": command.chapter.title or "Bản nháp cần duyệt thủ công",
            "content": draft_content,
            "analysis": last_analysis.model_dump() if last_analysis else None
        }
        await update_job(
            job_id=job_id,
            status="NEEDS_MANUAL_REVIEW",
            current_step=None,
            progress=100,
            chapter_id=chapter_id,
            result_payload=result,
            completed_at=datetime.now(UTC)
        )
        await publish_redis_stream(job_id, "completed", result)
        return result

    async def _fail_job(self, job_id: str, error_message: str):
        await update_job(
            job_id=job_id,
            status="FAILED",
            current_step=None,
            progress=100,
            error_payload={"message": error_message},
            completed_at=datetime.now(UTC)
        )
        await publish_redis_stream(job_id, "status", {"status": "FAILED", "error": error_message})

    async def _check_job_cancelled(self, job_id: str) -> str:
        job = await get_job(job_id)
        if job:
            return job.get("status")
        return "GENERATING"


def build_orchestrator(gateway: LLMGateway) -> StoryGenerationOrchestrator:
    return StoryGenerationOrchestrator(
        planner=StoryPlanner(gateway),
        retriever=StoryRetriever(gateway),
        prompt_builder=PromptBuilder(),
        gateway=gateway,
        analyzer=StoryAnalyzer(gateway)
    )
