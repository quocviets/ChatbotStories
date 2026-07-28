from typing import Any, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class ChapterOptions(BaseModel):
    title: Optional[str] = None
    target_word_count: int = Field(default=2000, ge=300, le=10000)
    pov_character_id: Optional[str] = None
    tone: Optional[str] = None
    chapter_tone_override: Optional[str] = None
    master_tone: Optional[str] = None
    master_outline: Optional[str] = None
    condensed_outline: Optional[str] = None
    character_wiki: Optional[dict[str, Any]] = None


class GenerationConfig(BaseModel):
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=6000, ge=256, le=32000)
    max_revision_attempts: int = Field(default=3, ge=0, le=5)
    auto_analyze: bool = True


class GenerateChapterRequest(BaseModel):
    request: str = Field(..., min_length=5, max_length=5000)
    model: str
    mode: Literal["SYNC", "ASYNC"] = "ASYNC"
    chapter: ChapterOptions = ChapterOptions()
    generation_config: GenerationConfig = GenerationConfig()
    constraints: list[str] = []
    metadata: dict[str, str] = {}


class StoryChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=20000)


class StoryChatRequest(BaseModel):
    message: str = Field(..., min_length=5, max_length=5000)
    model: str
    thread_id: Optional[UUID] = None
    thread_title: str = Field(default="Chat", min_length=1, max_length=200)
    history: list[StoryChatMessage] = Field(default_factory=list, max_length=30)
    master_outline: str = Field(default="", max_length=20000)
    master_tone: str = Field(default="", max_length=2000)


class StoryChatThreadSaveRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    messages: list[StoryChatMessage] = Field(default_factory=list, max_length=500)


class RenameChapterRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class ExportChatChapterRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=100000)
    model: str = Field(default="gemini-long-context", min_length=1, max_length=100)
    thread_id: UUID
    message_index: int = Field(..., ge=0)


class RegenerateChapterRequest(BaseModel):
    base_version_id: str
    feedback: str
    model: Optional[str] = None
    preserve: list[str] = []


class ContinueChapterRequest(BaseModel):
    request: str
    model: str
    target_word_count: int = 1000
    generation_config: GenerationConfig = GenerationConfig()


class FeedbackRequest(BaseModel):
    version_id: str
    action: Literal["APPROVE", "REJECT", "REVISION_REQUESTED"]
    feedback: Optional[str] = None
    auto_regenerate: bool = False
    model: Optional[str] = None


class ApproveRequest(BaseModel):
    version_id: str
    approved_by: str
    update_memory: bool = True


# Analysis Models
class Issue(BaseModel):
    id: Optional[str] = None
    type: str  # CONTEXT_ISSUE, PLANNER_ISSUE, WRITING_ISSUE, POLICY_ISSUE
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    description: str
    suggested_action: Optional[str] = None
    location: Optional[dict[str, Any]] = None


class AnalysisResult(BaseModel):
    passed: bool
    score: int
    issues: list[Issue] = []
    primary_issue_type: Optional[str] = None


# LLM Models
class LLMUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class LLMRequest(BaseModel):
    model: str
    system_prompt: str
    messages: list[dict[str, str]]
    temperature: float = 0.8
    max_tokens: int = 4096
    response_format: str = "text"
    metadata: dict[str, Any] = {}


class LLMResponse(BaseModel):
    provider: str
    model: str
    content: str
    finish_reason: Optional[str] = None
    usage: LLMUsage = LLMUsage()
    latency_ms: int = 0
    raw_response_id: Optional[str] = None
