import sys
import os
import asyncio
import logging
from datetime import datetime
from uuid import UUID, uuid4
import threading
import json
import queue

from flask import Flask, jsonify, request, Response, send_from_directory
from flask_cors import CORS
from a2wsgi import WSGIMiddleware

# Dynamically resolve and prepend the absolute path of the AI_engine project
ENGINE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../AI_engine"))
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

# Import from app inside AI_engine project
from app.config import MODEL_REGISTRY
from app.infrastructure.db.postgres_client import (
    init_postgres, save_job, get_job, update_job,
    save_chapter_version, get_latest_chapter_version, get_chapter_versions,
    get_chapter_version_by_id
)
from app.infrastructure.redis.redis_client import init_redis, get_redis
from app.workers.generation_worker import worker_loop, submit_job_to_queue, process_enqueued_job

from app.application.dto.story_dtos import (
    GenerateChapterRequest, FeedbackRequest, ApproveRequest, 
    ContinueChapterRequest, RegenerateChapterRequest, LLMRequest
)
from app.application.commands.story_commands import (
    GenerateChapterCommand, ContinueChapterCommand
)
from app.infrastructure.llm.llm_gateway import LLMGateway
from app.pipeline.planner import StoryPlanner
from app.pipeline.retriever import StoryRetriever
from app.pipeline.prompt_builder import PromptBuilder
from app.pipeline.writer import StoryWriter
from app.pipeline.analyzer import StoryAnalyzer
from app.pipeline.issue_classifier import IssueClassifier
from app.pipeline.memory_manager import MemoryManager
from app.application.orchestrators.story_generation_orchestrator import StoryGenerationOrchestrator

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Persistent Event Loop thread for Async IO Operations ---
bg_loop = asyncio.new_event_loop()

def start_bg_loop():
    asyncio.set_event_loop(bg_loop)
    bg_loop.run_forever()

bg_thread = threading.Thread(target=start_bg_loop, daemon=True)
bg_thread.start()

def run_async(coro):
    """Utility helper to run async coroutines in the dedicated background loop."""
    future = asyncio.run_coroutine_threadsafe(coro, bg_loop)
    return future.result()

# --- Initialize Database, Redis and Workers inside background loop thread ---
async def init_services():
    logger.info("Connecting to Postgres & Redis inside background thread loop...")
    await init_postgres()
    await init_redis()
    logger.info("Starting background worker loop...")
    asyncio.create_task(worker_loop())
    logger.info("AI Story Engine background services running.")

run_async(init_services())

# --- Version Resolution Helper ---
async def resolve_chapter_version_helper(chapter_id: str, version_id_or_num: str) -> dict | None:
    try:
        UUID(version_id_or_num)
        version = await get_chapter_version_by_id(version_id_or_num)
        if version:
            return version
    except ValueError:
        pass

    version_num = int(version_id_or_num) if version_id_or_num.isdigit() else 1
    from app.infrastructure.db.postgres_client import get_chapter_version
    return await get_chapter_version(chapter_id, version_num)

# --- Flask App Instantiation ---
static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
flask_app = Flask(__name__, static_folder=static_dir, static_url_path="/static")
CORS(flask_app)

@flask_app.route("/")
def read_index():
    return send_from_directory(static_dir, "index.html")

# --- API Endpoints ---

@flask_app.route("/api/v1/ai/models", methods=["GET"])
def list_models():
    models_list = []
    for alias, spec in MODEL_REGISTRY.items():
        models_list.append({
            "alias": alias,
            "provider": spec["provider"],
            "enabled": spec["enabled"],
            "capabilities": [c.upper() for c in spec["capabilities"]],
            "recommended_for": spec["recommended_for"]
        })
    return jsonify({
        "code": 200,
        "message": "Models retrieved successfully",
        "data": models_list
    })

@flask_app.route("/api/v1/ai/stories/<story_id>/chapters/generate", methods=["POST"])
def generate_chapter(story_id):
    idempotency_key = request.headers.get("Idempotency-Key")
    tenant_id = request.headers.get("X-Tenant-Id")
    user_id = request.headers.get("X-User-Id")
    
    if not idempotency_key or not tenant_id or not user_id:
        return jsonify({"detail": "Missing required headers: Idempotency-Key, X-Tenant-Id, X-User-Id"}), 400
        
    data = request.json or {}
    model_name = data.get("model")
    if model_name not in MODEL_REGISTRY:
        return jsonify({"detail": f"Model alias {model_name} is not registered in the system."}), 422
        
    try:
        body = GenerateChapterRequest(**data)
    except Exception as e:
        return jsonify({"detail": str(e)}), 422
        
    job_id = str(uuid4())
    
    async def run():
        job_db = await save_job(
            job_id=job_id,
            tenant_id=tenant_id,
            user_id=user_id,
            story_id=str(story_id),
            operation="GENERATE",
            status="QUEUED",
            model_alias=body.model,
            idempotency_key=idempotency_key,
            request_payload=body.model_dump(),
            max_attempts=body.generation_config.max_revision_attempts
        )
        
        if str(job_db["id"]) != job_id:
            return {
                "code": 200,
                "message": "Generation job already exists",
                "data": {
                    "job_id": str(job_db["id"]),
                    "story_id": str(job_db["story_id"]),
                    "status": job_db["status"],
                    "model": job_db["model_alias"],
                    "created_at": job_db["created_at"].isoformat() if hasattr(job_db["created_at"], "isoformat") else job_db["created_at"],
                    "status_url": f"/api/v1/ai/jobs/{job_db['id']}"
                }
            }, 200
            
        await submit_job_to_queue(job_id)
        return {
            "code": 202,
            "message": "Chapter generation job accepted",
            "data": {
                "job_id": job_id,
                "story_id": str(story_id),
                "status": "QUEUED",
                "model": body.model,
                "created_at": datetime.utcnow().isoformat() + "Z",
                "status_url": f"/api/v1/ai/jobs/{job_id}"
            }
        }, 202
        
    res, status_code = run_async(run())
    return jsonify(res), status_code

@flask_app.route("/api/v1/ai/stories/<story_id>/chapters/generate-sync", methods=["POST"])
def generate_chapter_sync(story_id):
    idempotency_key = request.headers.get("Idempotency-Key")
    tenant_id = request.headers.get("X-Tenant-Id")
    user_id = request.headers.get("X-User-Id")
    
    if not idempotency_key or not tenant_id or not user_id:
        return jsonify({"detail": "Missing required headers: Idempotency-Key, X-Tenant-Id, X-User-Id"}), 400
        
    data = request.json or {}
    try:
        body = GenerateChapterRequest(**data)
    except Exception as e:
        return jsonify({"detail": str(e)}), 422
        
    job_id = str(uuid4())
    
    async def run():
        await save_job(
            job_id=job_id,
            tenant_id=tenant_id,
            user_id=user_id,
            story_id=str(story_id),
            operation="GENERATE_SYNC",
            status="PROCESSING",
            model_alias=body.model,
            idempotency_key=idempotency_key,
            request_payload=body.model_dump(),
            max_attempts=body.generation_config.max_revision_attempts
        )
        
        gateway = LLMGateway()
        orchestrator = StoryGenerationOrchestrator(
            planner=StoryPlanner(gateway),
            retriever=StoryRetriever(gateway),
            prompt_builder=PromptBuilder(),
            writer=StoryWriter(gateway),
            analyzer=StoryAnalyzer(gateway),
            issue_classifier=IssueClassifier()
        )
        
        await process_enqueued_job(job_id, orchestrator)
        
        job_result = await get_job(job_id)
        if not job_result or job_result["status"] == "FAILED":
            return {"detail": f"Synchronous generation failed. Payload: {job_result.get('error_payload')}"}, 502
            
        return {
            "code": 200,
            "message": "Chapter generated successfully",
            "data": job_result.get("result_payload")
        }, 200
        
    res, status_code = run_async(run())
    return jsonify(res), status_code

@flask_app.route("/api/v1/ai/stories/<story_id>/chapters/<chapter_id>/continue", methods=["POST"])
def continue_chapter(story_id, chapter_id):
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        return jsonify({"detail": "Missing X-User-Id header"}), 400
        
    data = request.json or {}
    try:
        body = ContinueChapterRequest(**data)
    except Exception as e:
        return jsonify({"detail": str(e)}), 422
        
    async def run():
        latest_version = await get_latest_chapter_version(str(chapter_id))
        if not latest_version:
            return {"detail": "Chapter not found"}, 404
            
        system_prompt = (
            "Bạn là tác giả chuyên nghiệp. Hãy viết tiếp chương truyện dưới đây dựa theo yêu cầu của độc giả.\n"
            "Đảm bảo mạch văn trôi chảy nối tiếp hoàn hảo từ đoạn trước."
        )
        
        user_instruct = (
            f"[NỘI DUNG CHƯƠNG ĐÃ CÓ LƯU TRỮ]\n"
            f"{latest_version['content']}\n\n"
            f"[YÊU CẦU VIẾT TIẾP]\n"
            f"{body.request}\n\n"
            f"Độ dài viết thêm kỳ vọng: {body.target_word_count} từ.\n"
            f"Chỉ trả ra văn bản nội dung viết tiếp, không giải thích gì thêm."
        )
        
        llm_request = LLMRequest(
            model=body.model,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_instruct}],
            temperature=body.generation_config.temperature,
            max_tokens=body.generation_config.max_output_tokens
        )
        
        gateway = LLMGateway()
        response = await gateway.generate(body.model, llm_request)
        
        new_content = latest_version["content"] + "\n\n" + response.content
        new_version_num = latest_version["version_number"] + 1
        
        version_row = await save_chapter_version(
            chapter_id=str(chapter_id),
            version_number=new_version_num,
            content=new_content,
            status="READY_FOR_REVIEW",
            model_alias=body.model,
            prompt_template_version="chapter-continuer-v1.0",
            generation_metadata={
                "provider": response.provider,
                "model": response.model,
                "latency_ms": response.latency_ms,
                "usage": response.usage.model_dump()
            },
            created_by=user_id
        )
        
        return {
            "code": 200,
            "message": "Chapter continuation generated",
            "data": {
                "chapter_id": str(chapter_id),
                "version_id": str(version_row["id"]),
                "status": "READY_FOR_REVIEW",
                "content": new_content
            }
        }, 200
        
    res, status_code = run_async(run())
    return jsonify(res), status_code

@flask_app.route("/api/v1/ai/stories/<story_id>/chapters/<chapter_id>/regenerate", methods=["POST"])
def regenerate_chapter(story_id, chapter_id):
    tenant_id = request.headers.get("X-Tenant-Id")
    user_id = request.headers.get("X-User-Id")
    if not tenant_id or not user_id:
        return jsonify({"detail": "Missing X-Tenant-Id or X-User-Id header"}), 400
        
    data = request.json or {}
    try:
        body = RegenerateChapterRequest(**data)
    except Exception as e:
        return jsonify({"detail": str(e)}), 422
        
    async def run():
        base_version = await resolve_chapter_version_helper(str(chapter_id), body.base_version_id)
        if not base_version:
            base_version = await get_latest_chapter_version(str(chapter_id))
            
        if not base_version:
            return {"detail": "Base chapter version not found"}, 404
            
        model_name = body.model or base_version["model_alias"] or "claude-sonnet"
        
        command = GenerateChapterCommand(
            story_id=str(story_id),
            tenant_id=tenant_id,
            user_id=user_id,
            idempotency_key=str(uuid4()),
            request=body.feedback,
            model=model_name,
            mode="SYNC",
            chapter=GenerateChapterRequest(request="re-gen", model=model_name).chapter,
            generation_config=GenerateChapterRequest(request="re-gen", model=model_name).generation_config,
            constraints=[],
            metadata={}
        )
        
        plan = {
            "chapter_goal": body.feedback,
            "chapter_type": "revision",
            "target_word_count": 2000,
            "pov_character": "character_001",
            "required_scenes": [],
            "continuity_constraints": [],
            "ending_hook": ""
        }
        
        gateway = LLMGateway()
        retriever = StoryRetriever(gateway)
        analyzer = StoryAnalyzer(gateway)
        prompt_builder = PromptBuilder()
        
        context = await retriever.retrieve(str(story_id), command, plan)
        system_prompt, user_instruct = await prompt_builder.build(
            command=command, plan=plan, context=context, preserve_feedback=body.feedback
        )
        
        llm_request = LLMRequest(
            model=model_name,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_instruct}],
            temperature=0.8,
            max_tokens=6000
        )
        
        llm_response = await gateway.generate(model_name, llm_request)
        analysis = await analyzer.analyze(str(story_id), llm_response.content, plan, context)
        
        versions = await get_chapter_versions(str(chapter_id))
        new_version_num = len(versions) + 1
        
        version_row = await save_chapter_version(
            chapter_id=str(chapter_id),
            version_number=new_version_num,
            content=llm_response.content,
            status="READY_FOR_REVIEW" if analysis.passed else "DRAFT",
            model_alias=model_name,
            prompt_template_version="chapter-regenerator-v1.0",
            generation_metadata={
                "provider": llm_response.provider,
                "model": llm_response.model,
                "latency_ms": llm_response.latency_ms,
                "usage": llm_response.usage.model_dump()
            },
            analysis_result=analysis.model_dump(),
            user_feedback=body.feedback,
            created_by=user_id
        )
        
        return {
            "code": 200,
            "message": "New chapter version generated successfully",
            "data": {
                "chapter_id": str(chapter_id),
                "version_id": str(version_row["id"]),
                "status": version_row["status"],
                "content": llm_response.content,
                "analysis": analysis.model_dump()
            }
        }, 200
        
    res, status_code = run_async(run())
    return jsonify(res), status_code

@flask_app.route("/api/v1/ai/stories/<story_id>/chapters/<chapter_id>/feedback", methods=["POST"])
def submit_feedback(story_id, chapter_id):
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        return jsonify({"detail": "Missing X-User-Id header"}), 400
        
    data = request.json or {}
    try:
        body = FeedbackRequest(**data)
    except Exception as e:
        return jsonify({"detail": str(e)}), 422
        
    async def run():
        chapter_ver = await resolve_chapter_version_helper(str(chapter_id), body.version_id)
        if not chapter_ver:
            return {"detail": "Chapter version not found"}, 404
            
        version_num = chapter_ver["version_number"]
        gateway = LLMGateway()
        memory_manager = MemoryManager(gateway)
        
        new_status = "READY_FOR_REVIEW"
        if body.action == "APPROVE":
            new_status = "APPROVED"
            await memory_manager.update_memory_after_approval(
                story_id=str(story_id),
                chapter_id=str(chapter_id),
                chapter_content=chapter_ver["content"],
                version_number=version_num
            )
        elif body.action == "REJECT":
            new_status = "REJECTED"
        elif body.action == "REVISION_REQUESTED":
            new_status = "REVISION_REQUESTED"
            
        updated_ver = await save_chapter_version(
            chapter_id=str(chapter_id),
            version_number=version_num,
            content=chapter_ver["content"],
            status=new_status,
            model_alias=chapter_ver["model_alias"],
            prompt_template_version=chapter_ver["prompt_template_version"],
            generation_metadata=chapter_ver["generation_metadata"],
            analysis_result=chapter_ver["analysis_result"],
            user_feedback=body.feedback,
            created_by=user_id
        )
        
        return {
            "code": 200,
            "message": f"Feedback processed. Chapter state is now {new_status}",
            "data": {
                "chapter_id": str(chapter_id),
                "version_id": str(updated_ver["id"]),
                "status": updated_ver["status"]
            }
        }, 200
        
    res, status_code = run_async(run())
    return jsonify(res), status_code

@flask_app.route("/api/v1/ai/stories/<story_id>/chapters/<chapter_id>/approve", methods=["POST"])
def approve_chapter(story_id, chapter_id):
    data = request.json or {}
    try:
        body = ApproveRequest(**data)
    except Exception as e:
        return jsonify({"detail": str(e)}), 422
        
    async def run():
        chapter_ver = await resolve_chapter_version_helper(str(chapter_id), body.version_id)
        if not chapter_ver:
            return {"detail": "Chapter version not found"}, 404
            
        version_num = chapter_ver["version_number"]
        gateway = LLMGateway()
        memory_manager = MemoryManager(gateway)
        
        await save_chapter_version(
            chapter_id=str(chapter_id),
            version_number=version_num,
            content=chapter_ver["content"],
            status="APPROVED",
            model_alias=chapter_ver["model_alias"],
            prompt_template_version=chapter_ver["prompt_template_version"],
            generation_metadata=chapter_ver["generation_metadata"],
            analysis_result=chapter_ver["analysis_result"],
            created_by=body.approved_by
        )
        
        memory_update_status = "SKIPPED"
        if body.update_memory:
            await memory_manager.update_memory_after_approval(
                story_id=str(story_id),
                chapter_id=str(chapter_id),
                chapter_content=chapter_ver["content"],
                version_number=version_num
            )
            memory_update_status = "COMPLETED"
            
        return {
            "code": 200,
            "message": "Chapter approved and memory updated",
            "data": {
                "chapter_id": str(chapter_id),
                "version_id": str(body.version_id),
                "status": "APPROVED",
                "memory_update_status": memory_update_status
            }
        }, 200
        
    res, status_code = run_async(run())
    return jsonify(res), status_code

@flask_app.route("/api/v1/ai/stories/<story_id>/chapters/<chapter_id>/analyze", methods=["POST"])
def analyze_chapter(story_id, chapter_id):
    data = request.json or {}
    try:
        body = FeedbackRequest(**data)
    except Exception as e:
        return jsonify({"detail": str(e)}), 422
        
    async def run():
        chapter_ver = await resolve_chapter_version_helper(str(chapter_id), body.version_id)
        if not chapter_ver:
            return {"detail": "Chapter version not found"}, 404
            
        version_num = chapter_ver["version_number"]
        gateway = LLMGateway()
        retriever = StoryRetriever(gateway)
        analyzer = StoryAnalyzer(gateway)
        
        dummy_plan = {
            "chapter_goal": "Kiểm tra độc lập",
            "chapter_type": "analysis",
            "target_word_count": 2000,
            "pov_character": "character_001",
            "required_scenes": [],
            "continuity_constraints": []
        }
        
        command = GenerateChapterCommand(
            story_id=str(story_id), tenant_id="system", user_id="system", idempotency_key="system",
            request="analyze", model="gpt-writing", mode="SYNC", 
            chapter=GenerateChapterRequest(request="a", model="g").chapter,
            generation_config=GenerateChapterRequest(request="a", model="g").generation_config,
            constraints=[], metadata={}
        )
        
        context = await retriever.retrieve(str(story_id), command, dummy_plan)
        analysis = await analyzer.analyze(str(story_id), chapter_ver["content"], dummy_plan, context)
        
        await save_chapter_version(
            chapter_id=str(chapter_id),
            version_number=version_num,
            content=chapter_ver["content"],
            status=chapter_ver["status"],
            model_alias=chapter_ver["model_alias"],
            prompt_template_version=chapter_ver["prompt_template_version"],
            generation_metadata=chapter_ver["generation_metadata"],
            analysis_result=analysis.model_dump(),
            created_by=chapter_ver["created_by"]
        )
        
        return {
            "code": 200,
            "message": "Chapter analyzed successfully",
            "data": analysis.model_dump()
        }, 200
        
    res, status_code = run_async(run())
    return jsonify(res), status_code

@flask_app.route("/api/v1/ai/jobs/<job_id>", methods=["GET"])
def get_job_status(job_id):
    async def run():
        job = await get_job(str(job_id))
        if not job:
            return {"detail": f"Job {job_id} not found."}, 404
            
        return {
            "code": 200,
            "message": "Job retrieved successfully",
            "data": {
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
        }, 200
        
    res, status_code = run_async(run())
    return jsonify(res), status_code

@flask_app.route("/api/v1/ai/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    async def run():
        job = await get_job(str(job_id))
        if not job:
            return {"detail": "Job not found"}, 404
            
        if job["status"] not in ("QUEUED", "PLANNING", "RETRIEVING", "BUILDING_PROMPT", "GENERATING", "ANALYZING"):
            return {"detail": f"Job {job_id} is already in a terminal state: {job['status']}"}, 409
            
        await update_job(job_id=str(job_id), status="CANCELLED", completed_at=datetime.utcnow())
        logger.info(f"Cancellation request recorded for job {job_id}.")
        
        return {
            "code": 200,
            "message": "Job cancellation request recorded."
        }, 200
        
    res, status_code = run_async(run())
    return jsonify(res), status_code

@flask_app.route("/api/v1/ai/jobs/<job_id>/stream", methods=["GET"])
def stream_job(job_id):
    def event_generator():
        async def get_initial_state():
            job = await get_job(job_id)
            if job:
                return f"event: status\ndata: {json.dumps({'status': job['status'], 'progress': job['progress']}, ensure_ascii=False)}\n\n"
            return None
            
        init_evt = run_async(get_initial_state())
        if init_evt:
            yield init_evt
            
        import queue
        q = queue.Queue()
        
        async def redis_listener():
            try:
                redis = get_redis()
                pubsub = redis.pubsub()
                channel = f"ai:job:{job_id}:stream"
                await pubsub.subscribe(channel)
                logger.info(f"SSE Flask client subscribed to Redis channel: {channel}")
                
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        payload = json.loads(message["data"])
                        event = payload["event"]
                        data = payload["data"]
                        
                        evt_str = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                        q.put(evt_str)
                        
                        if event == "completed" or (event == "status" and isinstance(data, dict) and data.get("status") in ("COMPLETED", "FAILED", "CANCELLED", "NEEDS_MANUAL_REVIEW")):
                            q.put(None)
                            break
            except Exception as e:
                logger.error(f"Error in Redis listener thread: {e}")
                q.put(None)
            finally:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.close()
                except Exception:
                    pass
                    
        asyncio.run_coroutine_threadsafe(redis_listener(), bg_loop)
        
        while True:
            try:
                msg = q.get(timeout=30.0)
                if msg is None:
                    break
                yield msg
            except queue.Empty:
                yield ": keep-alive\n\n"
                
    return Response(event_generator(), mimetype="text/event-stream")

# --- Wrap Flask App with WSGIMiddleware for ASGI Uvicorn compatibility ---
app = WSGIMiddleware(flask_app)
