from typing import Literal, Optional
from pydantic import BaseModel
from app.application.dto.story_dtos import ChapterOptions, GenerationConfig

class GenerateChapterCommand(BaseModel):
    story_id: str
    tenant_id: str
    user_id: str
    idempotency_key: str
    request: str
    model: str
    mode: Literal["SYNC", "ASYNC"]
    chapter: ChapterOptions
    generation_config: GenerationConfig
    constraints: list[str]
    metadata: dict[str, str]


class RegenerateChapterCommand(BaseModel):
    story_id: str
    chapter_id: str
    tenant_id: str
    user_id: str
    base_version_id: str
    feedback: str
    model: Optional[str] = None
    preserve: list[str] = []


class ContinueChapterCommand(BaseModel):
    story_id: str
    chapter_id: str
    tenant_id: str
    user_id: str
    request: str
    model: str
    target_word_count: int
    generation_config: GenerationConfig
