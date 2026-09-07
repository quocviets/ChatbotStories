from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StoryCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    master_tone: str = Field(default="", max_length=2000)
    master_outline: str = Field(default="", max_length=20000)


class StoryUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    master_tone: str | None = Field(default=None, max_length=2000)
    master_outline: str | None = Field(default=None, max_length=20000)
    archived: bool | None = None


class LegacyStoryImportItem(BaseModel):
    id: UUID
    title: str = Field(..., min_length=1, max_length=200)
    master_tone: str = Field(default="", max_length=2000)
    master_outline: str = Field(default="", max_length=20000)
    created_at: datetime | None = None
    archived_at: datetime | None = None


class LegacyStoryImportRequest(BaseModel):
    stories: list[LegacyStoryImportItem] = Field(default_factory=list, max_length=100)


class CharacterWikiEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = "Đang sống"
    role: str = ""
    speech_rhythm: str | None = None
    word_choice: str | None = None
    conflict_style: str | None = None
    emotional_leak: str | None = None
    avoids: list[str] = Field(default_factory=list)


class ScenePlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scene_id: str
    objective: str
    conflict: str = ""
    participants: list[str] = Field(default_factory=list)
    location: str = ""
    mandatory_facts: list[str] = Field(default_factory=list)
    state_before: list[str] = Field(default_factory=list)
    state_after: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)


class ChapterPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chapter_goal: str
    chapter_type: str = "standard"
    target_word_count: int = Field(default=2000, ge=300, le=10000)
    pov_character: str = "Nhân vật chính"
    tone: str = "Thô mộc, tự nhiên, bộc trực"
    required_scenes: list[ScenePlan] = Field(default_factory=list)
    continuity_constraints: list[str] = Field(default_factory=list)
    ending_hook: str = ""


class ChapterOptions(BaseModel):
    title: str | None = None
    target_word_count: int = Field(default=2000, ge=300, le=10000)
    pov_character_id: str | None = None
    tone: str | None = None
    chapter_tone_override: str | None = None
    master_tone: str | None = None
    master_outline: str | None = None
    condensed_outline: str | None = None
    character_wiki: dict[str, CharacterWikiEntry | Any] | None = None


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
    thread_id: UUID | None = None
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
    model: str | None = None
    preserve: list[str] = []


class ContinueChapterRequest(BaseModel):
    request: str
    model: str
    target_word_count: int = 1000
    generation_config: GenerationConfig = GenerationConfig()


class FeedbackRequest(BaseModel):
    version_id: str
    action: Literal["APPROVE", "REJECT", "REVISION_REQUESTED"]
    feedback: str | None = None
    auto_regenerate: bool = False
    model: str | None = None


class ApproveRequest(BaseModel):
    version_id: str
    approved_by: str
    update_memory: bool = True


# Analysis Models
class Issue(BaseModel):
    id: str | None = None
    type: str  # CONTEXT_ISSUE, PLANNER_ISSUE, WRITING_ISSUE, POLICY_ISSUE
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    description: str
    suggested_action: str | None = None
    location: dict[str, Any] | None = None


HARD_ANALYSIS_ISSUE_TYPES = frozenset(
    {
        "EMPTY_OR_BROKEN_OUTPUT",
        "MANDATORY_EVENT_LOSS",
        "DIRECT_CONTINUITY_CONTRADICTION",
        "CHAPTER_ORDER_VIOLATION",
        "CORE_WORLD_RULE_VIOLATION",
        "REQUIRED_POV_VIOLATION",
        "PLOT_ALIGNMENT_VIOLATION",
    }
)


def is_blocking_analysis_issue(issue: Issue) -> bool:
    return issue.severity == "HIGH" and issue.type.upper() in HARD_ANALYSIS_ISSUE_TYPES


class AnalysisResult(BaseModel):
    passed: bool
    score: int
    issues: list[Issue] = Field(default_factory=list)
    primary_issue_type: str | None = None
    warnings: list[Issue] = Field(default_factory=list)
    blocking_issues: list[Issue] = Field(default_factory=list)
    needs_manual_review: bool = False

    @model_validator(mode="after")
    def classify_issues(self):
        if not self.issues:
            self.issues = [*self.blocking_issues, *self.warnings]
        self.blocking_issues = [issue for issue in self.issues if is_blocking_analysis_issue(issue)]
        self.warnings = [issue for issue in self.issues if not is_blocking_analysis_issue(issue)]
        self.needs_manual_review = self.needs_manual_review or any(
            issue.severity == "HIGH" for issue in self.warnings
        )
        return self


NarrativeIssueType = Literal[
    "redundant_explanation",
    "show_dont_tell_violation",
    "summary_like_prose",
    "unnatural_dialogue",
    "expository_dialogue",
    "repeated_information",
    "authorial_conclusion",
    "overexplained_emotion",
    "generic_ai_phrase",
    "overly_complete_reasoning",
    "pacing_drag",
    "character_voice_mismatch",
    "unnecessary_internal_monologue",
    "purple_prose",
    "continuity_risk",
]
NarrativeIssueSeverity = Literal["high", "medium", "low"]


class NarrativeIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    type: NarrativeIssueType
    severity: NarrativeIssueSeverity
    paragraph_ids: list[str] = Field(min_length=1)
    evidence: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=2000)
    revision_instruction: str = Field(min_length=1, max_length=2000)
    must_preserve: list[str] = Field(default_factory=list)


class NarrativeCritique(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    needs_revision: bool
    issues: list[NarrativeIssue] = Field(default_factory=list)
    fallback_reason: str | None = None

    @model_validator(mode="after")
    def require_issues_for_revision(self):
        if self.needs_revision and not self.issues:
            raise ValueError("needs_revision=true requires at least one issue")
        return self


class ParagraphRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    paragraph_id: str = Field(min_length=1)
    revised_text: str = Field(min_length=1)


class TargetedRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    revisions: list[ParagraphRevision] = Field(min_length=1)


# LLM Models
class LLMUsage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    usage_available: bool = False


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
    finish_reason: str | None = None
    usage: LLMUsage = Field(default_factory=LLMUsage)
    latency_ms: int = 0
    raw_response_id: str | None = None
    fallback_from: str | None = None
    fallback_reason: str | None = None
