from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from app.application.dto.story_dtos import FeedbackRequest, GenerateChapterRequest
from app.application.commands.story_commands import GenerateChapterCommand
from app.infrastructure.db.postgres_client import get_chapter_version, save_chapter_version, get_chapter_version_by_id
from app.infrastructure.llm.llm_gateway import LLMGateway
from app.pipeline.analyzer import StoryAnalyzer
from app.pipeline.retriever import StoryRetriever

async def resolve_chapter_version_helper(chapter_id: str, version_id_or_num: str) -> dict | None:
    try:
        UUID(version_id_or_num)
        version = await get_chapter_version_by_id(version_id_or_num)
        if version:
            return version
    except ValueError:
        pass

    version_num = int(version_id_or_num) if version_id_or_num.isdigit() else 1
    return await get_chapter_version(chapter_id, version_num)

router = APIRouter(prefix="/stories", tags=["Story Analysis"])

def get_gateway() -> LLMGateway:
    return LLMGateway()

def get_retriever(gateway=Depends(get_gateway)) -> StoryRetriever:
    return StoryRetriever(gateway)

def get_analyzer(gateway=Depends(get_gateway)) -> StoryAnalyzer:
    return StoryAnalyzer(gateway)


@router.post(
    "/{story_id}/chapters/{chapter_id}/analyze",
    status_code=status.HTTP_200_OK
)
async def analyze_chapter(
    story_id: UUID,
    chapter_id: UUID,
    body: FeedbackRequest,
    analyzer=Depends(get_analyzer),
    retriever=Depends(get_retriever)
):
    chapter_ver = await resolve_chapter_version_helper(str(chapter_id), body.version_id)
    if not chapter_ver:
        raise HTTPException(status_code=404, detail="Chapter version not found")
    version_num = chapter_ver["version_number"]
        
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
    }
