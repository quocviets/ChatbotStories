from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class ChapterOptions(BaseModel):
    title: Optional[str] = None
    target_word_count: int = Field(default=2000, ge=300, le=10000)
    pov_character_id: Optional[str] = None
    tone: Optional[str] = None


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
    top_p: Optional[float] = None
    stop: Optional[list[str]] = None
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


# Generation Results and Job Models
class GenerationResult(BaseModel):
    chapter_id: str
    version_id: str
    status: str
    title: Optional[str] = None
    content: Optional[str] = None
    analysis: Optional[AnalysisResult] = None
    generation: Optional[dict[str, Any]] = None


class JobState(BaseModel):
    job_id: str
    story_id: str
    chapter_id: Optional[str] = None
    status: str  # QUEUED, PLANNING, RETRIEVING, BUILDING_PROMPT, GENERATING, ANALYZING, READY_FOR_REVIEW, COMPLETED, FAILED, CANCELLED, NEEDS_MANUAL_REVIEW
    current_step: Optional[str] = None
    progress: int = 0
    attempt: int = 0
    max_attempts: int = 3
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
