import json
import logging
import asyncio
from uuid import UUID
from datetime import UTC, datetime
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.v1.responses import api_response
from app.infrastructure.db.postgres_client import get_job, update_job
from app.infrastructure.redis.redis_client import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/{job_id}", status_code=status.HTTP_200_OK)
async def get_job_status(job_id: UUID):
    job = await get_job(str(job_id))
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found."
        )
        
    return api_response(
        200,
        "Job retrieved successfully",
        data={
            "job_id": str(job["id"]),
            "story_id": str(job["story_id"]),
            "chapter_id": str(job["chapter_id"]) if job["chapter_id"] else None,
            "status": job["status"],
            "current_step": job["current_step"],
            "progress": job["progress"],
            "attempt": job["attempt"],
            "max_attempts": job["max_attempts"],
            "result": job.get("result_payload"),
            "error": job.get("error_payload") 
        }
    )


@router.post("/{job_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_job(job_id: UUID):
    job = await get_job(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] not in ("QUEUED", "PLANNING", "RETRIEVING", "BUILDING_PROMPT", "GENERATING", "ANALYZING"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job {job_id} is already in a terminal state: {job['status']}"
        )

    cancelled = await update_job(
        job_id=str(job_id), status="CANCELLED", progress=100, completed_at=datetime.now(UTC)
    )
    if not cancelled:
        raise HTTPException(status_code=409, detail="Job changed state before cancellation completed")
    logger.info(f"Cancellation request recorded for job {job_id}.")
    
    return api_response(200, "Job cancellation request recorded.")


@router.get("/{job_id}/stream")
async def stream_job(job_id: UUID):
    """
    Subscribes to Redis Pub/Sub to listen to events for the specified job_id 
    and streams them to the client as Server-Sent Events.
    """
    job = await get_job(str(job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator():
        pubsub = None
        channel = f"ai:job:{job_id}:stream"
        try:
            current_job = job
            if current_job["status"] not in ("COMPLETED", "FAILED", "CANCELLED", "NEEDS_MANUAL_REVIEW"):
                pubsub = get_redis().pubsub()
                await pubsub.subscribe(channel)
                logger.info(f"SSE Client subscribed to Redis channel: {channel}")
                current_job = await get_job(str(job_id)) or current_job

            yield f"event: status\ndata: {json.dumps({'status': current_job['status'], 'progress': current_job['progress']}, ensure_ascii=False)}\n\n"
            if current_job["status"] in ("COMPLETED", "NEEDS_MANUAL_REVIEW"):
                yield f"event: completed\ndata: {json.dumps(current_job.get('result_payload') or {}, ensure_ascii=False)}\n\n"
                return
            if current_job["status"] in ("FAILED", "CANCELLED"):
                return
            
            async for message in pubsub.listen():
                if message["type"] == "message":
                    payload = json.loads(message["data"])
                    event = payload["event"]
                    data = payload["data"]
                    
                    yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                    
                    # Graceful disconnect conditions
                    if event == "completed" or (event == "status" and isinstance(data, dict) and data.get("status") in ("COMPLETED", "FAILED", "CANCELLED", "NEEDS_MANUAL_REVIEW")):
                        break
        except asyncio.CancelledError:
            logger.debug(f"SSE Client connection cancelled for job {job_id}.")
        except Exception as e:
            logger.error(f"SSE connection error for job {job_id}: {e}")
        finally:
            if pubsub:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.close()
                except Exception:
                    pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")
