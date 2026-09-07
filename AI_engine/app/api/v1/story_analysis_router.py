from uuid import UUID

from app.api.v1.responses import api_response
from app.application.commands.story_commands import GenerateChapterCommand
from app.application.dto.story_dtos import ChapterOptions, FeedbackRequest, GenerationConfig
from app.infrastructure.db.postgres_client import (
    resolve_story_chapter_version,
    update_chapter_version,
)
from app.infrastructure.llm.llm_gateway import LLMGateway
from app.infrastructure.vector_store.pgvector_store import search_memories_vector
from app.pipeline.analyzer import StoryAnalyzer
from app.pipeline.retriever import StoryRetriever
from fastapi import APIRouter, Depends, HTTPException, Query, status

router = APIRouter(prefix="/stories", tags=["Story Analysis"])


def get_gateway() -> LLMGateway:
    return LLMGateway()


def get_retriever(gateway=Depends(get_gateway)) -> StoryRetriever:
    return StoryRetriever(gateway)


def get_analyzer(gateway=Depends(get_gateway)) -> StoryAnalyzer:
    return StoryAnalyzer(gateway)


@router.post("/{story_id}/chapters/{chapter_id}/analyze", status_code=status.HTTP_200_OK)
async def analyze_chapter(
    story_id: UUID,
    chapter_id: UUID,
    body: FeedbackRequest,
    analyzer=Depends(get_analyzer),
    retriever=Depends(get_retriever),
):
    chapter_ver = await resolve_story_chapter_version(
        str(story_id), str(chapter_id), body.version_id
    )
    if not chapter_ver:
        raise HTTPException(status_code=404, detail="Chapter version not found")
    dummy_plan = {
        "chapter_goal": "Kiểm tra độc lập",
        "chapter_type": "analysis",
        "target_word_count": 2000,
        "pov_character": "character_001",
        "required_scenes": [],
        "continuity_constraints": [],
    }

    command = GenerateChapterCommand(
        story_id=str(story_id),
        tenant_id="system",
        user_id="system",
        idempotency_key="system",
        request="analyze",
        model="gpt-writing",
        mode="SYNC",
        chapter=ChapterOptions(),
        generation_config=GenerationConfig(),
        constraints=[],
        metadata={},
    )

    context = await retriever.retrieve(str(story_id), command, dummy_plan)
    analysis = await analyzer.analyze(str(story_id), chapter_ver["content"], dummy_plan, context)

    updated = await update_chapter_version(
        str(chapter_id),
        chapter_ver,
        story_id=str(story_id),
        analysis_result=analysis.model_dump(),
        user_feedback=None,
    )
    if not updated:
        raise HTTPException(status_code=410, detail="Chapter was deleted.")

    return api_response(200, "Chapter analyzed successfully", data=analysis.model_dump())


@router.get("/{story_id}/lore/search", status_code=status.HTTP_200_OK)
async def search_story_lore(
    story_id: UUID,
    query: str = Query(..., min_length=2, max_length=500),
    limit: int = Query(8, ge=1, le=20),
    gateway=Depends(get_gateway),
):
    embedding = await gateway.get_embeddings(query)
    memories = await search_memories_vector(str(story_id), embedding, limit)
    results = [
        {
            "id": str(memory["id"]),
            "chapter_id": str(memory["chapter_id"]) if memory["chapter_id"] else None,
            "type": memory["memory_type"],
            "content": memory["content"],
            "similarity": float(memory["similarity"])
            if memory.get("similarity") is not None
            else None,
        }
        for memory in memories
    ]
    return api_response(200, "Lore search completed", data=results)
