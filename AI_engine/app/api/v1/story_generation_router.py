from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.api.v1.responses import api_response
from app.application.commands.story_commands import GenerateChapterCommand
from app.application.dto.story_dtos import (
    ApproveRequest,
    ChapterOptions,
    ContinueChapterRequest,
    ExportChatChapterRequest,
    FeedbackRequest,
    GenerateChapterRequest,
    GenerationConfig,
    LegacyStoryImportRequest,
    LLMRequest,
    RegenerateChapterRequest,
    RenameChapterRequest,
    StoryChatRequest,
    StoryChatThreadSaveRequest,
    StoryCreateRequest,
    StoryUpdateRequest,
)
from app.application.orchestrators.story_generation_orchestrator import (
    StoryGenerationOrchestrator,
    build_orchestrator,
)
from app.config import MODEL_REGISTRY
from app.infrastructure.db.postgres_client import (
    append_chat_message,
    attach_job_chapter,
    create_story_chapter,
    delete_chat_thread,
    get_job,
    get_story_chapter,
    get_story_chat_threads,
    import_legacy_stories,
    list_deleted_chapter_sources,
    list_stories,
    list_story_chapters,
    rename_chapter,
    resolve_story_chapter_version,
    save_chapter_version,
    save_chat_thread,
    save_job,
    save_next_chapter_version,
    update_chapter_version,
    update_job,
    update_story,
)
from app.infrastructure.db.postgres_client import create_story as create_story_record
from app.infrastructure.db.postgres_client import delete_chapter as delete_chapter_data
from app.infrastructure.llm.llm_gateway import LLMGateway
from app.pipeline.analyzer import StoryAnalyzer
from app.pipeline.memory_manager import MemoryManager
from app.pipeline.prompt_builder import PromptBuilder
from app.pipeline.retriever import StoryRetriever
from app.workers.generation_worker import process_enqueued_job, submit_job_to_queue
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/stories", tags=["Story Generation"])


# Dependencies
def get_gateway() -> LLMGateway:
    return LLMGateway()


def get_orchestrator(gateway=Depends(get_gateway)) -> StoryGenerationOrchestrator:
    return build_orchestrator(gateway)


def get_retriever(gateway=Depends(get_gateway)) -> StoryRetriever:
    return StoryRetriever(gateway)


def get_analyzer(gateway=Depends(get_gateway)) -> StoryAnalyzer:
    return StoryAnalyzer(gateway)


def get_memory_manager(gateway=Depends(get_gateway)) -> MemoryManager:
    return MemoryManager(gateway)


def _story_payload(story: dict) -> dict:
    return {
        "id": str(story["id"]),
        "title": story["title"],
        "master_tone": story.get("master_tone") or "",
        "master_outline": story.get("master_outline") or "",
        "created_at": story.get("created_at"),
        "updated_at": story.get("updated_at"),
        "archived_at": story.get("archived_at"),
        "chapter_count": story.get("chapter_count", 0),
        "chat_count": story.get("chat_count", 0),
    }


@router.get("", status_code=status.HTTP_200_OK)
async def get_stories(
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
    user_id: str = Header(..., alias="X-User-Id"),
):
    stories = await list_stories(tenant_id, user_id)
    return api_response(
        200,
        "Stories loaded",
        data=[_story_payload(story) for story in stories],
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_story(
    body: StoryCreateRequest,
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
    user_id: str = Header(..., alias="X-User-Id"),
):
    story = await create_story_record(
        tenant_id=tenant_id,
        user_id=user_id,
        title=body.title,
        master_tone=body.master_tone,
        master_outline=body.master_outline,
    )
    return api_response(201, "Story created", data=_story_payload(story))


@router.post("/import", status_code=status.HTTP_200_OK)
async def import_stories(
    body: LegacyStoryImportRequest,
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
    user_id: str = Header(..., alias="X-User-Id"),
):
    imported = await import_legacy_stories(
        tenant_id,
        user_id,
        [story.model_dump() for story in body.stories],
    )
    return api_response(200, "Legacy stories imported", data={"imported": imported})


@router.patch("/{story_id}", status_code=status.HTTP_200_OK)
async def patch_story(
    story_id: UUID,
    body: StoryUpdateRequest,
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
    user_id: str = Header(..., alias="X-User-Id"),
):
    story = await update_story(
        str(story_id),
        tenant_id,
        user_id,
        **body.model_dump(exclude_unset=True),
    )
    if not story:
        raise HTTPException(status_code=404, detail="Story not found.")
    return api_response(200, "Story updated", data=_story_payload(story))


@router.get("/{story_id}/chats", status_code=status.HTTP_200_OK)
async def list_story_chats(story_id: UUID):
    return api_response(200, "Story chats loaded", data=await get_story_chat_threads(str(story_id)))


@router.put("/{story_id}/chats/{thread_id}", status_code=status.HTTP_200_OK)
async def save_story_chat(story_id: UUID, thread_id: UUID, body: StoryChatThreadSaveRequest):
    await save_chat_thread(
        str(story_id),
        str(thread_id),
        body.title,
        [message.model_dump() for message in body.messages],
    )
    return api_response(200, "Story chat saved", data={"thread_id": str(thread_id)})


@router.delete("/{story_id}/chats/{thread_id}", status_code=status.HTTP_200_OK)
async def delete_story_chat(story_id: UUID, thread_id: UUID):
    deleted = await delete_chat_thread(str(story_id), str(thread_id))
    return api_response(
        200,
        "Story chat deleted" if deleted else "Story chat already absent",
        data={"deleted": deleted},
    )


@router.delete("/{story_id}/chapters/{chapter_id}", status_code=status.HTTP_200_OK)
async def delete_story_chapter(story_id: UUID, chapter_id: UUID):
    deleted = await delete_chapter_data(str(story_id), str(chapter_id))
    return api_response(
        200, "Chapter deleted" if deleted else "Chapter already absent", data={"deleted": deleted}
    )


@router.get("/{story_id}/chapters", status_code=status.HTTP_200_OK)
async def list_chapters(story_id: UUID):
    chapters = []
    for chapter in await list_story_chapters(str(story_id)):
        metadata = chapter.get("generation_metadata") or {}
        source = metadata.get("source") or metadata
        chapters.append(
            {
                "chapter_id": str(chapter["chapter_id"]),
                "chapter_number": chapter["chapter_number"],
                "version_id": str(chapter["version_id"]),
                "title": chapter["title"],
                "content": chapter["content"],
                "model": chapter.get("model_alias") or chapter.get("chapter_model_alias"),
                "status": chapter["status"],
                "thread_id": (
                    str(chapter["source_thread_id"])
                    if chapter.get("source_thread_id")
                    else source.get("thread_id")
                ),
                "message_index": (
                    chapter["source_message_index"]
                    if chapter.get("source_message_index") is not None
                    else source.get("message_index")
                ),
            }
        )
    deleted_sources = [
        {
            "chapter_id": str(source["chapter_id"]),
            "thread_id": str(source["source_thread_id"]),
            "message_index": source["source_message_index"],
        }
        for source in await list_deleted_chapter_sources(str(story_id))
    ]
    return api_response(
        200,
        "Story chapters loaded",
        data=chapters,
        deleted_sources=deleted_sources,
    )


@router.patch("/{story_id}/chapters/{chapter_id}", status_code=status.HTTP_200_OK)
async def rename_story_chapter(story_id: UUID, chapter_id: UUID, body: RenameChapterRequest):
    renamed = await rename_chapter(str(story_id), str(chapter_id), body.title)
    if not renamed:
        raise HTTPException(status_code=404, detail="Chapter not found in this story.")
    return api_response(200, "Chapter renamed", data={"title": body.title})


@router.post("/{story_id}/chapters/from-chat", status_code=status.HTTP_201_CREATED)
async def export_chat_message_as_chapter(
    story_id: UUID,
    body: ExportChatChapterRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
    user_id: str = Header(..., alias="X-User-Id"),
):
    job_id, chapter_id = str(uuid4()), str(uuid4())
    request_payload = {
        "chapter": {"title": body.title},
        "source": {
            "type": "chat",
            "thread_id": str(body.thread_id),
            "message_index": body.message_index,
        },
    }
    job = await save_job(
        job_id=job_id,
        tenant_id=tenant_id,
        user_id=user_id,
        story_id=str(story_id),
        operation="CHAT_EXPORT",
        status="PROCESSING",
        model_alias=body.model,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
        max_attempts=0,
    )
    if str(job["id"]) != job_id:
        if job.get("result_payload"):
            return api_response(200, "Chat message already exported", data=job["result_payload"])
        raise HTTPException(status_code=409, detail="Chat export is already processing.")

    chapter = await create_story_chapter(
        story_id=str(story_id),
        chapter_id=chapter_id,
        title=body.title,
        source_thread_id=str(body.thread_id),
        source_message_index=body.message_index,
        model_alias=body.model,
    )
    if not await attach_job_chapter(job_id, chapter_id):
        raise HTTPException(status_code=409, detail="Chat export was cancelled.")

    version = await save_chapter_version(
        chapter_id=chapter_id,
        story_id=str(story_id),
        version_number=1,
        content=body.content,
        status="READY_FOR_REVIEW",
        model_alias=body.model,
        prompt_template_version="chat-export-v1",
        generation_metadata=request_payload["source"],
        created_by=user_id,
    )
    if not version:
        raise HTTPException(status_code=410, detail="Chapter was deleted before it could be saved.")
    result = {
        "chapter_id": chapter_id,
        "version_id": str(version["id"]),
        "title": chapter["title"],
        "content": body.content,
        "status": "READY_FOR_REVIEW",
        **request_payload["source"],
    }
    await update_job(
        job_id=job_id,
        status="COMPLETED",
        progress=100,
        chapter_id=chapter_id,
        result_payload=result,
        completed_at=datetime.now(UTC),
    )
    return api_response(201, "Chat message exported as chapter", data=result)


@router.get("/{story_id}/chapters/{chapter_id}", status_code=status.HTTP_200_OK)
async def read_story_chapter(story_id: UUID, chapter_id: UUID):
    chapter = await get_story_chapter(str(story_id), str(chapter_id))
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found in this story.")
    metadata = chapter.get("generation_metadata") or {}
    source = metadata.get("source") or metadata
    return api_response(
        200,
        "Chapter loaded",
        data={
            "chapter_id": str(chapter["chapter_id"]),
            "version_id": str(chapter["id"]),
            "content": chapter["content"],
            "model": chapter.get("model_alias"),
            "status": chapter["status"],
            "thread_id": source.get("thread_id"),
            "message_index": source.get("message_index"),
        },
    )


@router.post("/{story_id}/chat", status_code=status.HTTP_200_OK, summary="Trao đổi ý tưởng truyện")
async def chat_about_story(story_id: UUID, body: StoryChatRequest, gateway=Depends(get_gateway)):
    if body.model not in MODEL_REGISTRY:
        raise HTTPException(
            status_code=422, detail=f"Model alias {body.model} is not registered in the system."
        )

    thread_id = body.thread_id or uuid4()
    await append_chat_message(
        str(story_id), str(thread_id), body.thread_title, "user", body.message
    )

    system_prompt = (
        "Bạn là trợ lý phát triển ý tưởng truyện. Đây là cuộc thảo luận, không phải nội dung chương. "
        "Hãy giúp người dùng làm rõ nhân vật, thế giới, tình tiết và các quyết định đã thống nhất để dùng khi viết chương sau.\n"
        f"Giọng văn của bộ truyện: {body.master_tone or 'Chưa xác định'}\n"
        f"Đề cương tổng quát: {body.master_outline or 'Chưa có'}"
    )
    messages = [message.model_dump() for message in body.history[-20:]]
    messages.append({"role": "user", "content": body.message})
    response = await gateway.generate(
        body.model,
        LLMRequest(
            model=body.model,
            system_prompt=system_prompt,
            messages=messages,
            temperature=0.8,
            max_tokens=3000,
            metadata={"target_word_count": 180},
        ),
    )
    await append_chat_message(
        str(story_id), str(thread_id), body.thread_title, "assistant", response.content
    )
    return api_response(
        200, "Story chat completed", data={"thread_id": str(thread_id), "reply": response.content}
    )


@router.post(
    "/{story_id}/chapters/generate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sinh chương truyện bất đồng bộ (Async Job)",
    description="Khởi tạo một tiến trình sinh chương truyện chạy ngầm dưới dạng job. Trả về mã Job ID lập tức cho Client để lắng nghe stream chữ.",
)
async def generate_chapter(
    story_id: UUID,
    body: GenerateChapterRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
    user_id: str = Header(..., alias="X-User-Id"),
):
    if body.model not in MODEL_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Model alias {body.model} is not registered in the system.",
        )

    job_id = str(uuid4())

    # Save job record (handles idempotency key uniqueness)
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
        max_attempts=body.generation_config.max_revision_attempts,
    )

    # Check if duplicate job was already created
    if str(job_db["id"]) != job_id:
        return api_response(
            200,
            "Generation job already exists",
            data={
                "job_id": str(job_db["id"]),
                "story_id": str(job_db["story_id"]),
                "status": job_db["status"],
                "model": job_db["model_alias"],
                "created_at": job_db["created_at"].isoformat()
                if hasattr(job_db["created_at"], "isoformat")
                else job_db["created_at"],
                "status_url": f"/api/v1/ai/jobs/{job_db['id']}",
            },
        )

    # Enqueue task
    await submit_job_to_queue(job_id)

    return api_response(
        202,
        "Chapter generation job accepted",
        data={
            "job_id": job_id,
            "story_id": str(story_id),
            "status": "QUEUED",
            "model": body.model,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "status_url": f"/api/v1/ai/jobs/{job_id}",
        },
    )


@router.post(
    "/{story_id}/chapters/generate-sync",
    status_code=status.HTTP_200_OK,
    summary="Sinh chương truyện đồng bộ (Sync Job)",
    description="Khởi chạy tiến trình sinh chương truyện đồng bộ, đợi Worker chạy qua toàn bộ pipeline xử lý rồi trả bản nháp hoàn tất kèm kết quả chấm điểm.",
)
async def generate_chapter_sync(
    story_id: UUID,
    body: GenerateChapterRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
    user_id: str = Header(..., alias="X-User-Id"),
    orchestrator=Depends(get_orchestrator),
):
    job_id = str(uuid4())

    job_db = await save_job(
        job_id=job_id,
        tenant_id=tenant_id,
        user_id=user_id,
        story_id=str(story_id),
        operation="GENERATE_SYNC",
        status="PROCESSING",
        model_alias=body.model,
        idempotency_key=idempotency_key,
        request_payload=body.model_dump(),
        max_attempts=body.generation_config.max_revision_attempts,
    )

    if str(job_db["id"]) != job_id:
        if job_db.get("result_payload"):
            return api_response(
                200, "Generation job already completed", data=job_db["result_payload"]
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Generation job {job_db['id']} already exists for this idempotency key.",
        )

    # Process task directly in synchronous fashion
    await process_enqueued_job(job_id, orchestrator)

    job_result = await get_job(job_id)
    if not job_result or job_result["status"] == "FAILED":
        error_payload = (
            job_result.get("error_payload")
            if job_result
            else {"message": "Job record disappeared."}
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Synchronous generation failed. Payload: {error_payload}",
        )

    return api_response(
        200, "Chapter generated successfully", data=job_result.get("result_payload")
    )


@router.post("/{story_id}/chapters/{chapter_id}/continue", status_code=status.HTTP_200_OK)
async def continue_chapter(
    story_id: UUID,
    chapter_id: UUID,
    body: ContinueChapterRequest,
    user_id: str = Header(..., alias="X-User-Id"),
    gateway=Depends(get_gateway),
):
    latest_version = await get_story_chapter(str(story_id), str(chapter_id))
    if not latest_version:
        raise HTTPException(status_code=404, detail="Chapter not found")

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
        f"Chỉ trả ra văn bản nội dung viết tiếp, không giải thích gì thêm.\n"
        f"Dùng văn bản thuần; không dùng Markdown hoặc ký hiệu định dạng như *, ** hay #."
    )

    llm_request = LLMRequest(
        model=body.model,
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_instruct}],
        temperature=body.generation_config.temperature,
        max_tokens=body.generation_config.max_output_tokens,
    )

    response = await gateway.generate(body.model, llm_request)

    new_content = latest_version["content"] + "\n\n" + response.content
    version_row = await save_next_chapter_version(
        story_id=str(story_id),
        chapter_id=str(chapter_id),
        content=new_content,
        status="READY_FOR_REVIEW",
        model_alias=body.model,
        prompt_template_version="chapter-continuer-v1.0",
        generation_metadata={
            "provider": response.provider,
            "model": response.model,
            "latency_ms": response.latency_ms,
            "usage": response.usage.model_dump(),
            "source": (latest_version.get("generation_metadata") or {}).get("source"),
        },
        created_by=user_id,
    )
    if not version_row:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Chapter was deleted while the continuation was being generated.",
        )

    return api_response(
        200,
        "Chapter continuation generated",
        data={
            "chapter_id": str(chapter_id),
            "version_id": str(version_row["id"]),
            "status": "READY_FOR_REVIEW",
            "content": new_content,
        },
    )


@router.post("/{story_id}/chapters/{chapter_id}/regenerate", status_code=status.HTTP_200_OK)
async def regenerate_chapter(
    story_id: UUID,
    chapter_id: UUID,
    body: RegenerateChapterRequest,
    tenant_id: str = Header(..., alias="X-Tenant-Id"),
    user_id: str = Header(..., alias="X-User-Id"),
    gateway=Depends(get_gateway),
    prompt_builder=Depends(PromptBuilder),
    retriever=Depends(get_retriever),
    analyzer=Depends(get_analyzer),
):
    base_version = await resolve_story_chapter_version(
        str(story_id), str(chapter_id), body.base_version_id
    )
    if not base_version:
        base_version = await get_story_chapter(str(story_id), str(chapter_id))

    if not base_version:
        raise HTTPException(status_code=404, detail="Base chapter version not found")

    model_name = body.model or base_version["model_alias"] or "claude-sonnet"
    command = GenerateChapterCommand(
        story_id=str(story_id),
        tenant_id=tenant_id,
        user_id=user_id,
        idempotency_key=str(uuid4()),
        request=body.feedback,
        model=model_name,
        mode="SYNC",
        chapter=ChapterOptions(),
        generation_config=GenerationConfig(),
        constraints=[],
        metadata={},
    )

    plan = {
        "chapter_goal": body.feedback,
        "chapter_type": "revision",
        "target_word_count": 2000,
        "pov_character": "character_001",
        "required_scenes": [],
        "continuity_constraints": [],
        "ending_hook": "",
    }

    context = await retriever.retrieve(str(story_id), command, plan)
    system_prompt, user_instruct = await prompt_builder.build(
        command=command, plan=plan, context=context, preserve_feedback=body.feedback
    )
    user_instruct += (
        "\n\n[CURRENT DRAFT TO REVISE]\n"
        f"{base_version['content']}\n\n"
        "[REVISION MODE]\n"
        "Chỉnh bản nháp trên theo đúng phản hồi. Chỉ trả toàn bộ nội dung chương sau khi sửa."
    )

    llm_request = LLMRequest(
        model=model_name,
        system_prompt=system_prompt,
        messages=[{"role": "user", "content": user_instruct}],
        temperature=0.8,
        max_tokens=6000,
    )

    llm_response = await gateway.generate(model_name, llm_request)
    analysis = await analyzer.analyze(str(story_id), llm_response.content, plan, context)

    version_row = await save_next_chapter_version(
        story_id=str(story_id),
        chapter_id=str(chapter_id),
        content=llm_response.content,
        status="READY_FOR_REVIEW" if analysis.passed else "DRAFT",
        model_alias=model_name,
        prompt_template_version="chapter-regenerator-v1.0",
        generation_metadata={
            "provider": llm_response.provider,
            "model": llm_response.model,
            "latency_ms": llm_response.latency_ms,
            "usage": llm_response.usage.model_dump(),
            "source": (base_version.get("generation_metadata") or {}).get("source"),
        },
        analysis_result=analysis.model_dump(),
        user_feedback=body.feedback,
        created_by=user_id,
    )
    if not version_row:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Chapter was deleted while regeneration was running.",
        )

    return api_response(
        200,
        "New chapter version generated successfully",
        data={
            "chapter_id": str(chapter_id),
            "version_id": str(version_row["id"]),
            "status": version_row["status"],
            "content": llm_response.content,
            "analysis": analysis.model_dump(),
        },
    )


@router.post("/{story_id}/chapters/{chapter_id}/feedback", status_code=status.HTTP_200_OK)
async def submit_feedback(
    story_id: UUID,
    chapter_id: UUID,
    body: FeedbackRequest,
    user_id: str = Header(..., alias="X-User-Id"),
    memory_manager=Depends(get_memory_manager),
):
    chapter_ver = await resolve_story_chapter_version(
        str(story_id), str(chapter_id), body.version_id
    )
    if not chapter_ver:
        raise HTTPException(status_code=404, detail="Chapter version not found")
    version_num = chapter_ver["version_number"]

    new_status = "READY_FOR_REVIEW"
    should_update_memory = body.action == "APPROVE"
    if should_update_memory:
        new_status = "APPROVED"
    elif body.action == "REJECT":
        new_status = "REJECTED"
    elif body.action == "REVISION_REQUESTED":
        new_status = "REVISION_REQUESTED"

    updated_ver = await update_chapter_version(
        str(chapter_id),
        chapter_ver,
        story_id=str(story_id),
        status=new_status,
        user_feedback=body.feedback,
        created_by=user_id,
    )
    if not updated_ver:
        raise HTTPException(status_code=410, detail="Chapter was deleted.")
    if should_update_memory:
        await memory_manager.update_memory_after_approval(
            story_id=str(story_id),
            chapter_id=str(chapter_id),
            chapter_content=chapter_ver["content"],
            version_number=version_num,
        )

    return api_response(
        200,
        f"Feedback processed. Chapter state is now {new_status}",
        data={
            "chapter_id": str(chapter_id),
            "version_id": str(updated_ver["id"]),
            "status": updated_ver["status"],
        },
    )


@router.post("/{story_id}/chapters/{chapter_id}/approve", status_code=status.HTTP_200_OK)
async def approve_chapter(
    story_id: UUID,
    chapter_id: UUID,
    body: ApproveRequest,
    memory_manager=Depends(get_memory_manager),
):
    chapter_ver = await resolve_story_chapter_version(
        str(story_id), str(chapter_id), body.version_id
    )
    if not chapter_ver:
        raise HTTPException(status_code=404, detail="Chapter version not found")
    version_num = chapter_ver["version_number"]

    updated_ver = await update_chapter_version(
        str(chapter_id),
        chapter_ver,
        story_id=str(story_id),
        status="APPROVED",
        user_feedback=None,
        created_by=body.approved_by,
    )
    if not updated_ver:
        raise HTTPException(status_code=410, detail="Chapter was deleted.")

    memory_update_status = "SKIPPED"
    if body.update_memory:
        memory_result = await memory_manager.update_memory_after_approval(
            story_id=str(story_id),
            chapter_id=str(chapter_id),
            chapter_content=chapter_ver["content"],
            version_number=version_num,
        )
        memory_update_status = memory_result["status"]

    return api_response(
        200,
        "Chapter approved and memory updated",
        data={
            "chapter_id": str(chapter_id),
            "version_id": str(body.version_id),
            "status": "APPROVED",
            "memory_update_status": memory_update_status,
        },
    )


class UpdateVersionContentRequest(BaseModel):
    content: str


@router.put(
    "/{story_id}/chapters/{chapter_id}/versions/{version_id}",
    status_code=status.HTTP_200_OK,
    summary="Cập nhật nội dung bản thảo theo chỉnh sửa trực tiếp của người dùng",
)
async def update_chapter_version_content(
    story_id: UUID,
    chapter_id: UUID,
    version_id: str,
    body: UpdateVersionContentRequest,
    user_id: str = Header("system", alias="X-User-Id"),
):
    chapter_ver = await resolve_story_chapter_version(str(story_id), str(chapter_id), version_id)
    if not chapter_ver:
        raise HTTPException(status_code=404, detail="Chapter version not found")

    updated_ver = await update_chapter_version(
        str(chapter_id),
        chapter_ver,
        story_id=str(story_id),
        content=body.content,
        created_by=user_id,
    )
    if not updated_ver:
        raise HTTPException(status_code=410, detail="Chapter was deleted.")

    return api_response(
        200,
        "Chapter version content updated successfully",
        data={
            "chapter_id": str(chapter_id),
            "version_id": str(updated_ver["id"]),
            "status": updated_ver["status"],
            "content": updated_ver["content"],
        },
    )
