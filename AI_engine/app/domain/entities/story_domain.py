from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field
from app.domain.enums.story_enums import JobStatus, ChapterStatus

class Story(BaseModel):
    id: str
    title: str
    summary: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Chapter(BaseModel):
    id: str
    story_id: str
    title: Optional[str] = None
    target_word_count: int = 2000
    pov_character_id: Optional[str] = None
    tone: Optional[str] = None
    status: ChapterStatus = ChapterStatus.DRAFT
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChapterVersion(BaseModel):
    id: str
    chapter_id: str
    version_number: int
    content: str
    status: ChapterStatus
    model_alias: Optional[str] = None
    prompt_template_version: Optional[str] = None
    generation_metadata: Optional[dict[str, Any]] = None
    analysis_result: Optional[dict[str, Any]] = None
    user_feedback: Optional[str] = None
    created_by: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class StoryMemory(BaseModel):
    id: str
    story_id: str
    chapter_id: Optional[str] = None
    memory_type: str
    content: str
    metadata: Optional[dict[str, Any]] = None
    embedding: Optional[list[float]] = None
    importance_score: float = 0.5
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GenerationJob(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    story_id: str
    chapter_id: Optional[str] = None
    operation: str
    status: JobStatus
    current_step: Optional[str] = None
    model_alias: str
    provider: Optional[str] = None
    progress: int = 0
    attempt: int = 0
    max_attempts: int = 3
    idempotency_key: str
    request_payload: dict[str, Any]
    result_payload: Optional[dict[str, Any]] = None
    error_payload: Optional[dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
