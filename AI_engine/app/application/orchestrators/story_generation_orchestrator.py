import logging
import json
import traceback
from datetime import datetime
from uuid import uuid4
from typing import Optional, Any

from app.application.commands.story_commands import GenerateChapterCommand
from app.application.dto.story_dtos import AnalysisResult, LLMRequest
from app.infrastructure.db.postgres_client import update_job, save_chapter_version
from app.infrastructure.redis.redis_client import get_redis
from app.infrastructure.llm.llm_gateway import LLMGateway
from app.pipeline.planner import StoryPlanner
from app.pipeline.retriever import StoryRetriever
from app.pipeline.prompt_builder import PromptBuilder
from app.pipeline.writer import StoryWriter
from app.pipeline.analyzer import StoryAnalyzer
from app.pipeline.issue_classifier import IssueClassifier

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
        writer: StoryWriter,
        analyzer: StoryAnalyzer,
        issue_classifier: IssueClassifier
    ):
        self.planner = planner
        self.retriever = retriever
        self.prompt_builder = prompt_builder
        self.writer = writer
        self.analyzer = analyzer
        self.issue_classifier = issue_classifier

    async def execute(self, command: GenerateChapterCommand, job_id: str) -> dict:
        logger.info(f"Orchestrator started job {job_id} for story {command.story_id}")
        
        # 1. Update status to PLANNING
        await update_job(
            job_id=job_id,
            status="PLANNING",
            current_step="PLANNER",
            progress=10,
            started_at=datetime.utcnow()
        )
        await publish_redis_stream(job_id, "status", {"status": "PLANNING", "progress": 10})

        # Step 1: PLANNER
        try:
            recent_chapters = await get_recent_chapters_content_from_db(command.story_id)
            query_vector = await self.retriever.gateway.get_embeddings(command.request)
            relevant_memories = await search_memories_from_vector(command.story_id, query_vector)
            
            plan = await self.planner.create_plan(command, recent_chapters, relevant_memories)
            logger.info(f"Planner complete for job {job_id}")
        except Exception as e:
            error_msg = f"Error during planning phase: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            await self._fail_job(job_id, error_msg)
            return {"status": "FAILED", "error": error_msg}

        # 2. Update status to RETRIEVING
        await update_job(job_id=job_id, status="RETRIEVING", current_step="RETRIEVER", progress=30)
        await publish_redis_stream(job_id, "status", {"status": "RETRIEVING", "progress": 30})

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
            await update_job(
                job_id=job_id,
                status="BUILDING_PROMPT",
                current_step="PROMPT_BUILDER",
                progress=40,
                attempt=attempts
            )
            await publish_redis_stream(job_id, "status", {"status": "BUILDING_PROMPT", "progress": 40})

            # Step 3: PROMPT BUILDER
            system_prompt, user_instruct = await self.prompt_builder.build(
                command=command,
                plan=plan,
                context=context,
                previous_analysis=last_analysis
            )

            # 4. Update status to GENERATING
            await update_job(job_id=job_id, status="GENERATING", current_step="LLM_WRITER", progress=50)
            await publish_redis_stream(job_id, "status", {"status": "GENERATING", "progress": 50})

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
                llm_response = await self.writer.write_draft(command.model, llm_request, stream_handler=stream_handler)
                draft_content = llm_response.content
                logger.info(f"Writer complete for job {job_id}, attempt {attempts}")
            except Exception as e:
                error_msg = f"Error during generation phase: {e}"
                logger.error(f"{error_msg}\n{traceback.format_exc()}")
                await self._fail_job(job_id, error_msg)
                return {"status": "FAILED", "error": error_msg}

            # If auto_analyze is false, bypass Analyzer
            if not command.generation_config.auto_analyze:
                version_row = await save_chapter_version(
                    chapter_id=chapter_id,
                    version_number=attempts + 1,
                    content=draft_content,
                    status="READY_FOR_REVIEW",
                    model_alias=command.model,
                    prompt_template_version="chapter-writer-v1.0",
                    generation_metadata={
                        "provider": llm_response.provider,
                        "model": llm_response.model,
                        "latency_ms": llm_response.latency_ms,
                        "usage": llm_response.usage.model_dump()
                    },
                    created_by=command.user_id
                )
                result = {
                    "chapter_id": chapter_id,
                    "version_id": str(version_row["id"]),
                    "status": "READY_FOR_REVIEW",
                    "title": command.chapter.title or "Bản nháp sinh bởi AI",
                    "content": draft_content,
                    "analysis": None
                }
                await update_job(
                    job_id=job_id,
                    status="COMPLETED",
                    current_step=None,
                    progress=100,
                    chapter_id=chapter_id,
                    result_payload=result,
                    completed_at=datetime.utcnow()
                )
                await publish_redis_stream(job_id, "completed", result)
                return result

            # 5. Update status to ANALYZING
            await update_job(job_id=job_id, status="ANALYZING", current_step="STORY_ANALYZER", progress=80)
            await publish_redis_stream(job_id, "status", {"status": "ANALYZING", "progress": 80})

            # Step 5: ANALYZER
            try:
                analysis = await self.analyzer.analyze(command.story_id, draft_content, plan, context, attempt=attempts)
                await publish_redis_stream(job_id, "analysis", analysis.model_dump())
                logger.info(f"Analyzer complete for job {job_id}, score {analysis.score}")
            except Exception as e:
                error_msg = f"Error during analysis phase: {e}"
                logger.error(f"{error_msg}\n{traceback.format_exc()}")
                await self._fail_job(job_id, error_msg)
                return {"status": "FAILED", "error": error_msg}

            # Save draft
            version_row = await save_chapter_version(
                chapter_id=chapter_id,
                version_number=attempts + 1,
                content=draft_content,
                status="READY_FOR_REVIEW" if analysis.passed else "DRAFT",
                model_alias=command.model,
                prompt_template_version="chapter-writer-v1.0",
                generation_metadata={
                    "provider": llm_response.provider,
                    "model": llm_response.model,
                    "latency_ms": llm_response.latency_ms,
                    "usage": llm_response.usage.model_dump()
                },
                analysis_result=analysis.model_dump(),
                created_by=command.user_id
            )

            if analysis.passed:
                result = {
                    "chapter_id": chapter_id,
                    "version_id": str(version_row["id"]),
                    "status": "READY_FOR_REVIEW",
                    "title": command.chapter.title or "Bản nháp sinh bởi AI",
                    "content": draft_content,
                    "analysis": analysis.model_dump()
                }
                await update_job(
                    job_id=job_id,
                    status="COMPLETED",
                    current_step=None,
                    progress=100,
                    chapter_id=chapter_id,
                    result_payload=result,
                    completed_at=datetime.utcnow()
                )
                await publish_redis_stream(job_id, "completed", result)
                return result

            # Retry: Classify issue and retrieve/plan more
            attempts += 1
            last_analysis = analysis
            
            if attempts <= max_attempts:
                issue_type = self.issue_classifier.classify_primary_issue(analysis)
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
            completed_at=datetime.utcnow()
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
            completed_at=datetime.utcnow()
        )
        await publish_redis_stream(job_id, "status", {"status": "FAILED", "error": error_message})

    async def _check_job_cancelled(self, job_id: str) -> str:
        job = await update_job(job_id=job_id, status="GENERATING") # Fetch current state
        if job:
            return job.get("status")
        return "GENERATING"


# --- Imports helper to bypass circular dependencies ---
async def get_recent_chapters_content_from_db(story_id: str) -> list[dict]:
    from app.infrastructure.db.postgres_client import get_recent_chapters_content
    return await get_recent_chapters_content(story_id, limit=3)


async def search_memories_from_vector(story_id: str, query_embedding: list[float]) -> list[dict]:
    from app.infrastructure.vector_store.pgvector_store import search_memories_vector
    return await search_memories_vector(story_id, query_embedding, limit=5)
