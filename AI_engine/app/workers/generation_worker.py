import asyncio
import logging
import traceback
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError
from app.application.commands.story_commands import GenerateChapterCommand
from app.application.dto.story_dtos import ChapterOptions, GenerationConfig
from app.infrastructure.db.postgres_client import get_job
from app.infrastructure.redis.redis_client import get_redis
from app.infrastructure.llm.llm_gateway import LLMGateway
from app.application.orchestrators.story_generation_orchestrator import StoryGenerationOrchestrator, build_orchestrator

logger = logging.getLogger(__name__)


async def submit_job_to_queue(job_id: str):
    """Enqueues a job_id for background processing via Redis queue."""
    redis = get_redis()
    await redis.rpush("ai_story_job_queue", job_id)
    logger.info(f"Enqueued job {job_id} to Redis queue.")


async def worker_loop():
    """Background worker processing jobs from the queue."""
    logger.info("Generation background worker started.")
    orchestrator = build_orchestrator(LLMGateway())

    redis = get_redis()
    while True:
        try:
            result = await redis.blpop("ai_story_job_queue", timeout=3.0)
            if result:
                job_id = result[1]
                await process_enqueued_job(job_id, orchestrator)
        except asyncio.CancelledError:
            logger.info("Background worker stopped.")
            break
        except (RedisTimeoutError, RedisConnectionError) as e:
            logger.warning("Redis queue temporarily unavailable; retrying: %s", e)
            await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Error in worker loop: {e}\n{traceback.format_exc()}")
            await asyncio.sleep(1)


async def process_enqueued_job(job_id: str, orchestrator: StoryGenerationOrchestrator):
    logger.info(f"Worker dequeued job {job_id} for processing.")
    
    job_db = await get_job(job_id)
    if not job_db:
        logger.error(f"Job {job_id} not found in DB.")
        return
        
    if job_db["status"] == "CANCELLED":
        logger.info(f"Job {job_id} was already cancelled.")
        return
        
    try:
        payload = job_db["request_payload"]
        
        chapter_opts = ChapterOptions(**payload.get("chapter", {}))
        gen_config = GenerationConfig(**payload.get("generation_config", {}))
        
        command = GenerateChapterCommand(
            story_id=str(job_db["story_id"]),
            tenant_id=job_db["tenant_id"],
            user_id=job_db["user_id"],
            idempotency_key=job_db["idempotency_key"],
            request=payload["request"],
            model=job_db["model_alias"],
            mode=payload.get("mode", "ASYNC"),
            chapter=chapter_opts,
            generation_config=gen_config,
            constraints=payload.get("constraints", []),
            metadata=payload.get("metadata", {})
        )
        
        await orchestrator.execute(command, job_id)
        logger.info(f"Job {job_id} processed successfully by orchestrator.")
        
    except Exception as e:
        logger.error(f"Orchestrator failed to process job {job_id}: {e}\n{traceback.format_exc()}")
        await orchestrator._fail_job(job_id, f"Processing failure: {str(e)}")
