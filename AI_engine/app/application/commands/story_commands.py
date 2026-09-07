from typing import Literal

from app.application.dto.story_dtos import ChapterOptions, GenerationConfig
from pydantic import BaseModel


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
