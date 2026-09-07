# AI Engine cho hệ thống viết truyện dài tập

**Product stage:** MVP-1

> **Reading order:** Read this product and architecture document first. Before changing code, continue with the WP-00 engineering foundation linked at the end, then read the active work-package specification.

## 1. Mục tiêu

AI Engine chịu trách nhiệm tạo, tiếp tục, phân tích và chỉnh sửa truyện dài tập dựa trên yêu cầu của người dùng. Engine phải bảo đảm:

- Giữ nhất quán nhân vật, bối cảnh, mốc thời gian và quy tắc thế giới.
- Có thể viết từng chương thay vì sinh toàn bộ truyện trong một lần.
- Có vòng lặp kiểm tra chất lượng trước khi trả kết quả cho người dùng.
- Lưu được memory dài hạn để tiếp tục truyện ở các phiên làm việc sau.
- Cho phép thay đổi nhiều nhà cung cấp và nhiều mô hình LLM.
- Cho phép Backend bên ngoài gọi qua RESTful API.
- Hỗ trợ regenerate, feedback, approve và versioning.

---

## 2. Vị trí của AI Engine trong hệ thống

```text
Client
  |
  v
FastAPI Backend
  |
  v
AI Engine
  |-----------------------> LLM Provider
  |                         - Claude
  |                         - OpenAI
  |                         - Gemini
  |                         - Local Model
  |
  |-----------------------> PostgreSQL + pgvector
  |                         - Story data
  |                         - Character data
  |                         - Chapter data
  |                         - Embeddings
  |                         - Metadata
  |
  |-----------------------> Redis
  |                         - Temporary context
  |                         - Prompt cache
  |                         - Generation state
  |
  |-----------------------> File Storage
                            - Exported stories
                            - Attachments
                            - Generated files
```

AI Engine không nên truy cập trực tiếp dữ liệu người dùng mà không thông qua các repository/service được định nghĩa rõ ràng.

---

## 3. Pipeline xử lý

```text
User Request
    |
    v
Planner
    |
    v
Retriever
    |
    v
Prompt Builder
    |
    v
LLM Writer <------> Redis
    |
    v
Draft Chapter
    |
    v
Story Analyzer
    |
    +------ Validation Passed ------> User Review
    |
    +------ Issue Detected ----------> Issue Classification
                                          |
                                          +--> Context Issue --> Retriever
                                          |
                                          +--> Planner Issue --> Planner
                                          |
                                          +--> Writing Issue --> Prompt Builder

User Review
    |
    +------ Approve ------> Memory Manager ------> Persistence Layer
    |
    +------ Reject/Feedback ---------------------> Prompt Builder
```

---

## 4. Các thành phần chính

## 4.1. Request Orchestrator

Điểm vào của AI Engine.

Nhiệm vụ:

- Kiểm tra request.
- Khởi tạo generation job.
- Gọi tuần tự các bước trong pipeline.
- Theo dõi trạng thái xử lý.
- Retry khi LLM lỗi tạm thời.
- Trả kết quả đồng bộ hoặc bất đồng bộ.

Interface đề xuất:

```python
class StoryGenerationOrchestrator:
    async def generate_chapter(self, command: GenerateChapterCommand) -> GenerationResult:
        ...

    async def regenerate_chapter(self, command: RegenerateChapterCommand) -> GenerationResult:
        ...

    async def analyze_chapter(self, command: AnalyzeChapterCommand) -> AnalysisResult:
        ...
```

---

## 4.2. Planner

Planner chuyển yêu cầu tự nhiên của người dùng thành kế hoạch viết có cấu trúc.

Input:

- Story ID.
- Yêu cầu người dùng.
- Thông tin chương trước.
- Story bible.
- Character state.
- Plot outline.

Output mẫu:

```json
{
  "chapter_goal": "Nhân vật chính phát hiện ra người cố vấn đang phản bội mình",
  "chapter_type": "revelation",
  "target_word_count": 2500,
  "pov_character": "character_001",
  "tone": "dark suspense",
  "required_scenes": [
    {
      "order": 1,
      "goal": "Nhân vật chính đột nhập thư phòng",
      "location": "old_castle_library",
      "characters": ["character_001"]
    },
    {
      "order": 2,
      "goal": "Tìm thấy thư mật",
      "location": "old_castle_library",
      "characters": ["character_001"]
    }
  ],
  "continuity_constraints": [
    "Nhân vật chính đang bị thương ở tay trái",
    "Không được tiết lộ toàn bộ thân phận phản diện"
  ],
  "ending_hook": "Người cố vấn xuất hiện phía sau nhân vật chính"
}
```

---

## 4.3. Retriever

Retriever tìm dữ liệu cần thiết từ PostgreSQL và pgvector.

Nguồn dữ liệu:

- Tóm tắt truyện.
- Các chương gần nhất.
- Character profiles.
- Character relationships.
- World rules.
- Locations.
- Unresolved plot points.
- User writing preferences.
- Các đoạn có ngữ nghĩa liên quan.

Chiến lược retrieval:

1. Lấy dữ liệu bắt buộc bằng SQL.
2. Lấy N chương gần nhất.
3. Semantic search bằng pgvector.
4. Rerank kết quả.
5. Giới hạn context theo token budget.

Output:

```json
{
  "story_summary": "...",
  "recent_chapters": [],
  "characters": [],
  "world_rules": [],
  "relevant_memories": [],
  "unresolved_plot_points": [],
  "token_usage_estimate": 9200
}
```

---

## 4.4. Prompt Builder

Prompt Builder hợp nhất:

- System prompt.
- Quy tắc viết truyện.
- Kế hoạch từ Planner.
- Context từ Retriever.
- Yêu cầu người dùng.
- Feedback của lần sinh trước.
- Cấu hình model.

Cấu trúc prompt đề xuất:

```text
[SYSTEM ROLE]
Bạn là tác giả truyện dài tập chuyên nghiệp.

[STORY RULES]
- Không thay đổi quy tắc thế giới.
- Không làm nhân vật biết thông tin họ chưa từng được biết.
- Giữ đúng ngôi kể và giọng văn.

[STORY BIBLE]
...

[CHARACTER STATE]
...

[RECENT EVENTS]
...

[CHAPTER PLAN]
...

[USER REQUEST]
...

[OUTPUT REQUIREMENTS]
- Chỉ trả nội dung chương.
- Không giải thích quá trình suy luận.
- Độ dài mục tiêu: 2500 từ.
```

Prompt Builder phải có version:

```text
prompt_template_version = chapter-writer-v1.3
```

---

## 4.5. LLM Writer

LLM Writer không phụ thuộc trực tiếp vào Claude, OpenAI hay Gemini. Nó chỉ gọi qua `LLMProvider` abstraction.

```python
from typing import Protocol


class LLMProvider(Protocol):
    async def generate(self, request: "LLMRequest") -> "LLMResponse":
        ...

    async def stream(self, request: "LLMRequest"):
        ...
```

Request chuẩn hóa:

```python
from pydantic import BaseModel, Field
from typing import Any


class LLMRequest(BaseModel):
    model: str
    system_prompt: str
    messages: list[dict[str, str]]
    temperature: float = Field(default=0.8, ge=0, le=2)
    max_tokens: int = 4096
    top_p: float | None = None
    stop: list[str] | None = None
    response_format: str = "text"
    metadata: dict[str, Any] = {}
```

Response chuẩn hóa:

```python
class LLMUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    provider: str
    model: str
    content: str
    finish_reason: str | None = None
    usage: LLMUsage
    latency_ms: int
    raw_response_id: str | None = None
```

---

## 4.6. Story Analyzer

Story Analyzer kiểm tra draft trước khi gửi cho user.

Các nhóm kiểm tra:

- Continuity: có mâu thuẫn với chương trước không.
- Character consistency: hành vi có đúng tính cách không.
- Timeline: thời gian có hợp lý không.
- World rules: có vi phạm quy tắc thế giới không.
- Plot alignment: có đi đúng outline không.
- Repetition: có lặp lại nội dung không.
- Style: đúng tone, POV và tense không.
- Safety: nội dung có vi phạm chính sách hệ thống không.

Output:

```json
{
  "passed": false,
  "score": 78,
  "issues": [
    {
      "type": "CONTEXT_ISSUE",
      "severity": "HIGH",
      "description": "Nhân vật A gọi đúng tên thật của B mặc dù chưa được tiết lộ",
      "suggested_action": "Retrieve chapter 8 and character knowledge state"
    }
  ]
}
```

Ngưỡng đề xuất:

```text
score >= 85 và không có HIGH issue => PASSED
```

---

## 4.7. Issue Classification

```text
CONTEXT_ISSUE
- Thiếu dữ liệu.
- Dữ liệu retrieved chưa đúng.
- Sai thông tin nhân vật hoặc sự kiện.
- Quay lại Retriever.

PLANNER_ISSUE
- Kế hoạch chương không hợp lý.
- Scene order sai.
- Mục tiêu chương không phù hợp.
- Quay lại Planner.

WRITING_ISSUE
- Văn phong chưa đạt.
- Lặp từ.
- Độ dài chưa đúng.
- Quay lại Prompt Builder hoặc LLM Writer.

POLICY_ISSUE
- Dừng xử lý hoặc yêu cầu điều chỉnh nội dung.
```

Giới hạn vòng lặp:

```text
max_revision_attempts = 3
```

Sau 3 lần vẫn lỗi, job chuyển sang `NEEDS_MANUAL_REVIEW`.

---

## 4.8. User Review

User có thể:

- Approve.
- Reject.
- Yêu cầu regenerate.
- Gửi feedback.
- Chỉnh sửa trực tiếp.
- Chọn một version cũ.

Trạng thái chapter:

```text
DRAFT
ANALYZING
READY_FOR_REVIEW
APPROVED
REJECTED
REVISION_REQUESTED
PUBLISHED
```

---

## 4.9. Memory Manager

Memory Manager chỉ cập nhật memory dài hạn sau khi user approve.

Dữ liệu cập nhật:

- Chapter summary.
- Character state changes.
- Relationship changes.
- New facts.
- New locations.
- Unresolved plot points.
- Resolved plot points.
- Timeline events.
- Vector embeddings.

Ví dụ:

```json
{
  "chapter_id": "chapter_012",
  "summary": "Nhân vật chính phát hiện người cố vấn phản bội",
  "character_updates": [
    {
      "character_id": "character_001",
      "changes": {
        "trust_in_mentor": 0,
        "left_hand_injury": "recovering"
      }
    }
  ],
  "new_facts": [
    "Người cố vấn làm việc cho Hội Đồng Bóng Tối"
  ],
  "new_plot_points": [
    {
      "title": "Danh tính chủ nhân của bức thư",
      "status": "OPEN"
    }
  ]
}
```

---

## 5. Thiết kế hỗ trợ nhiều LLM

## 5.1. Model Registry

Không để client gửi trực tiếp API key hoặc URL provider.

```yaml
models:
  claude-sonnet:
    provider: anthropic
    model_name: claude-sonnet
    enabled: true
    capabilities:
      - text_generation
      - long_context
      - structured_output
    default_temperature: 0.8
    max_output_tokens: 8192

  gpt-writing:
    provider: openai
    model_name: gpt-model-name
    enabled: true
    capabilities:
      - text_generation
      - structured_output

  gemini-long-context:
    provider: google
    model_name: gemini-model-name
    enabled: true
    capabilities:
      - text_generation
      - long_context

  local-llama:
    provider: ollama
    model_name: llama-model-name
    enabled: false
```

Client chỉ truyền alias:

```json
{
  "model": "claude-sonnet"
}
```

---

## 5.2. Provider Factory

```python
class LLMProviderFactory:
    def __init__(self, providers: dict[str, LLMProvider], model_registry: "ModelRegistry"):
        self.providers = providers
        self.model_registry = model_registry

    def get_provider(self, model_alias: str) -> tuple[LLMProvider, "ModelConfig"]:
        config = self.model_registry.get(model_alias)

        if not config.enabled:
            raise ValueError(f"Model {model_alias} is disabled")

        provider = self.providers.get(config.provider)
        if provider is None:
            raise ValueError(f"Provider {config.provider} is not configured")

        return provider, config
```

---

## 5.3. Routing Strategy

Có thể chọn model theo:

- User chọn trực tiếp.
- Loại tác vụ.
- Chi phí.
- Context length.
- Tốc độ.
- Provider đang khả dụng.

Ví dụ:

```text
Planner       -> model rẻ, structured output tốt
Retriever     -> embedding model
Writer        -> model viết tốt, context dài
Analyzer      -> model có khả năng reasoning và JSON output
Summarizer    -> model nhỏ, chi phí thấp
```

Cấu hình:

```yaml
routing:
  planner: gpt-writing
  writer: claude-sonnet
  analyzer: gpt-writing
  summarizer: local-llama
  embedding: text-embedding-model
```

---

## 5.4. Fallback

```yaml
fallbacks:
  claude-sonnet:
    - gpt-writing
    - gemini-long-context

  gpt-writing:
    - claude-sonnet
```

Chỉ fallback khi:

- Timeout.
- Rate limit.
- Provider unavailable.
- Internal provider error.

Không fallback khi request vi phạm validation hoặc policy.

---

## 6. RESTful API cho Backend bên ngoài

Base URL:

```text
/api/v1/ai
```

Authentication:

```http
Authorization: Bearer <service-token>
X-Request-Id: <uuid>
Idempotency-Key: <uuid>
```

Các header đề xuất:

```http
Content-Type: application/json
Accept: application/json
X-Tenant-Id: tenant_001
X-User-Id: user_001
```

---

## 6.1. Tạo chapter mới

```http
POST /api/v1/ai/stories/{storyId}/chapters/generate
```

Request:

```json
{
  "request": "Viết chương tiếp theo, tập trung vào việc Minh phát hiện người thầy phản bội",
  "model": "claude-sonnet",
  "mode": "ASYNC",
  "chapter": {
    "title": "Bức thư trong bóng tối",
    "target_word_count": 2500,
    "pov_character_id": "character_001",
    "tone": "dark suspense"
  },
  "generation_config": {
    "temperature": 0.85,
    "max_output_tokens": 6000,
    "max_revision_attempts": 3,
    "auto_analyze": true
  },
  "constraints": [
    "Không được để Minh biết danh tính phản diện cuối cùng",
    "Kết thúc bằng cliffhanger"
  ],
  "metadata": {
    "source": "web-editor"
  }
}
```

Response `202 Accepted`:

```json
{
  "code": 202,
  "message": "Chapter generation job accepted",
  "data": {
    "job_id": "job_01JXYZ",
    "story_id": "story_001",
    "status": "QUEUED",
    "model": "claude-sonnet",
    "created_at": "2026-07-16T08:30:00+07:00",
    "status_url": "/api/v1/ai/jobs/job_01JXYZ"
  }
}
```

---

## 6.2. Sinh chapter đồng bộ

```http
POST /api/v1/ai/stories/{storyId}/chapters/generate-sync
```

Chỉ dùng cho đoạn ngắn hoặc tác vụ có thời gian xử lý thấp.

Response `200 OK`:

```json
{
  "code": 200,
  "message": "Chapter generated successfully",
  "data": {
    "chapter_id": "chapter_012",
    "version_id": "version_001",
    "status": "READY_FOR_REVIEW",
    "title": "Bức thư trong bóng tối",
    "content": "...",
    "analysis": {
      "passed": true,
      "score": 91,
      "issues": []
    },
    "generation": {
      "provider": "anthropic",
      "model": "claude-sonnet",
      "input_tokens": 10420,
      "output_tokens": 3280,
      "latency_ms": 12450
    }
  }
}
```

---

## 6.3. Tiếp tục chapter hiện tại

```http
POST /api/v1/ai/stories/{storyId}/chapters/{chapterId}/continue
```

Request:

```json
{
  "request": "Viết tiếp khoảng 1000 từ, tăng nhịp độ và kết thúc bằng việc cánh cửa bí mật mở ra",
  "model": "gpt-writing",
  "target_word_count": 1000,
  "generation_config": {
    "temperature": 0.8
  }
}
```

---

## 6.4. Regenerate chapter

```http
POST /api/v1/ai/stories/{storyId}/chapters/{chapterId}/regenerate
```

Request:

```json
{
  "base_version_id": "version_001",
  "feedback": "Giảm hội thoại, tăng miêu tả tâm lý và làm đoạn kết bất ngờ hơn",
  "model": "gemini-long-context",
  "preserve": [
    "opening_scene",
    "main_plot_event"
  ]
}
```

Response tạo version mới, không ghi đè version cũ.

---

## 6.5. Phân tích chapter

```http
POST /api/v1/ai/stories/{storyId}/chapters/{chapterId}/analyze
```

Request:

```json
{
  "version_id": "version_002",
  "model": "gpt-writing",
  "checks": [
    "CONTINUITY",
    "CHARACTER_CONSISTENCY",
    "TIMELINE",
    "WORLD_RULES",
    "STYLE",
    "REPETITION"
  ]
}
```

Response:

```json
{
  "code": 200,
  "message": "Chapter analyzed successfully",
  "data": {
    "passed": false,
    "score": 79,
    "issues": [
      {
        "id": "issue_001",
        "type": "CONTEXT_ISSUE",
        "severity": "HIGH",
        "location": {
          "start_offset": 1200,
          "end_offset": 1325
        },
        "description": "Nhân vật biết một bí mật chưa được tiết lộ",
        "recommendation": "Rewrite this paragraph using only known character information"
      }
    ]
  }
}
```

---

## 6.6. Gửi feedback

```http
POST /api/v1/ai/stories/{storyId}/chapters/{chapterId}/feedback
```

Request:

```json
{
  "version_id": "version_002",
  "action": "REVISION_REQUESTED",
  "feedback": "Nhân vật phản diện xuất hiện quá sớm. Hãy chỉ để lại dấu vết.",
  "selected_text": {
    "start_offset": 1800,
    "end_offset": 2400
  },
  "auto_regenerate": true,
  "model": "claude-sonnet"
}
```

---

## 6.7. Approve chapter

```http
POST /api/v1/ai/stories/{storyId}/chapters/{chapterId}/approve
```

Request:

```json
{
  "version_id": "version_003",
  "approved_by": "user_001",
  "update_memory": true
}
```

Response:

```json
{
  "code": 200,
  "message": "Chapter approved and memory updated",
  "data": {
    "chapter_id": "chapter_012",
    "version_id": "version_003",
    "status": "APPROVED",
    "memory_update_status": "COMPLETED"
  }
}
```

---

## 6.8. Lấy trạng thái job

```http
GET /api/v1/ai/jobs/{jobId}
```

Response:

```json
{
  "code": 200,
  "message": "Job retrieved successfully",
  "data": {
    "job_id": "job_01JXYZ",
    "status": "ANALYZING",
    "progress": 80,
    "current_step": "STORY_ANALYZER",
    "attempt": 1,
    "max_attempts": 3,
    "result": null,
    "error": null
  }
}
```

Trạng thái job:

```text
QUEUED
PLANNING
RETRIEVING
BUILDING_PROMPT
GENERATING
ANALYZING
READY_FOR_REVIEW
COMPLETED
FAILED
CANCELLED
NEEDS_MANUAL_REVIEW
```

---

## 6.9. Hủy job

```http
POST /api/v1/ai/jobs/{jobId}/cancel
```

---

## 6.10. Streaming nội dung

Dùng Server-Sent Events:

```http
GET /api/v1/ai/jobs/{jobId}/stream
Accept: text/event-stream
```

Event mẫu:

```text
event: status
data: {"status":"GENERATING","progress":40}

event: token
data: {"content":"Trong căn phòng tối..."}

event: analysis
data: {"status":"ANALYZING","progress":85}

event: completed
data: {"chapter_id":"chapter_012","version_id":"version_003"}
```

---

## 6.11. Danh sách model

```http
GET /api/v1/ai/models
```

Response:

```json
{
  "code": 200,
  "message": "Models retrieved successfully",
  "data": [
    {
      "alias": "claude-sonnet",
      "provider": "anthropic",
      "enabled": true,
      "capabilities": ["TEXT_GENERATION", "LONG_CONTEXT"],
      "recommended_for": ["CHAPTER_WRITING"]
    },
    {
      "alias": "gpt-writing",
      "provider": "openai",
      "enabled": true,
      "capabilities": ["TEXT_GENERATION", "STRUCTURED_OUTPUT"],
      "recommended_for": ["PLANNING", "ANALYSIS"]
    }
  ]
}
```

---

## 7. FastAPI Router mẫu

```python
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1/ai", tags=["AI Story Engine"])


class ChapterOptions(BaseModel):
    title: str | None = None
    target_word_count: int = Field(default=2000, ge=300, le=10000)
    pov_character_id: str | None = None
    tone: str | None = None


class GenerationConfig(BaseModel):
    temperature: float = Field(default=0.8, ge=0, le=2)
    max_output_tokens: int = Field(default=6000, ge=256, le=32000)
    max_revision_attempts: int = Field(default=3, ge=0, le=5)
    auto_analyze: bool = True


class GenerateChapterRequest(BaseModel):
    request: str = Field(min_length=5, max_length=5000)
    model: str
    mode: Literal["SYNC", "ASYNC"] = "ASYNC"
    chapter: ChapterOptions = ChapterOptions()
    generation_config: GenerationConfig = GenerationConfig()
    constraints: list[str] = []
    metadata: dict[str, str] = {}


class FeedbackRequest(BaseModel):
    version_id: str
    action: Literal["APPROVE", "REJECT", "REVISION_REQUESTED"]
    feedback: str | None = None
    auto_regenerate: bool = False
    model: str | None = None


@router.post(
    "/stories/{story_id}/chapters/generate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_chapter(
    story_id: UUID,
    body: GenerateChapterRequest,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    tenant_id: str = Header(alias="X-Tenant-Id"),
    user_id: str = Header(alias="X-User-Id"),
    orchestrator=Depends(get_story_orchestrator),
):
    command = GenerateChapterCommand(
        story_id=str(story_id),
        tenant_id=tenant_id,
        user_id=user_id,
        idempotency_key=idempotency_key,
        **body.model_dump(),
    )

    job = await orchestrator.submit_generate_chapter(command)

    return {
        "code": 202,
        "message": "Chapter generation job accepted",
        "data": job.model_dump(),
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, job_service=Depends(get_job_service)):
    job = await job_service.get_required(job_id)
    return {
        "code": 200,
        "message": "Job retrieved successfully",
        "data": job.model_dump(),
    }


@router.post("/stories/{story_id}/chapters/{chapter_id}/feedback")
async def submit_feedback(
    story_id: UUID,
    chapter_id: UUID,
    body: FeedbackRequest,
    orchestrator=Depends(get_story_orchestrator),
):
    result = await orchestrator.handle_feedback(
        story_id=str(story_id),
        chapter_id=str(chapter_id),
        request=body,
    )

    return {
        "code": 200,
        "message": "Feedback processed successfully",
        "data": result.model_dump(),
    }
```

---

## 8. Service layer mẫu

```python
class StoryGenerationOrchestrator:
    def __init__(
        self,
        planner,
        retriever,
        prompt_builder,
        llm_gateway,
        analyzer,
        chapter_repository,
        job_repository,
    ):
        self.planner = planner
        self.retriever = retriever
        self.prompt_builder = prompt_builder
        self.llm_gateway = llm_gateway
        self.analyzer = analyzer
        self.chapter_repository = chapter_repository
        self.job_repository = job_repository

    async def execute(self, command: GenerateChapterCommand) -> GenerationResult:
        plan = await self.planner.create_plan(command)
        context = await self.retriever.retrieve(command.story_id, plan)

        attempts = 0
        last_analysis = None

        while attempts <= command.generation_config.max_revision_attempts:
            prompt = await self.prompt_builder.build(
                command=command,
                plan=plan,
                context=context,
                previous_analysis=last_analysis,
            )

            draft = await self.llm_gateway.generate(
                model_alias=command.model,
                prompt=prompt,
                config=command.generation_config,
            )

            if not command.generation_config.auto_analyze:
                return await self._save_draft(command, draft, None)

            analysis = await self.analyzer.analyze(
                story_id=command.story_id,
                draft=draft,
                plan=plan,
                context=context,
            )

            if analysis.passed:
                return await self._save_draft(command, draft, analysis)

            attempts += 1
            last_analysis = analysis

            if analysis.primary_issue_type == "CONTEXT_ISSUE":
                context = await self.retriever.retrieve_more(
                    story_id=command.story_id,
                    issues=analysis.issues,
                )
            elif analysis.primary_issue_type == "PLANNER_ISSUE":
                plan = await self.planner.revise_plan(plan, analysis.issues)

        return await self._save_for_manual_review(command, draft, last_analysis)
```

---

## 9. Database schema đề xuất

## 9.1. generation_jobs

```sql
CREATE TABLE generation_jobs (
    id UUID PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    story_id UUID NOT NULL,
    chapter_id UUID,
    operation VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL,
    current_step VARCHAR(50),
    model_alias VARCHAR(100) NOT NULL,
    provider VARCHAR(50),
    progress INTEGER NOT NULL DEFAULT 0,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    idempotency_key VARCHAR(150) NOT NULL,
    request_payload JSONB NOT NULL,
    result_payload JSONB,
    error_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    UNIQUE (tenant_id, idempotency_key)
);
```

## 9.2. chapter_versions

```sql
CREATE TABLE chapter_versions (
    id UUID PRIMARY KEY,
    chapter_id UUID NOT NULL,
    version_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    status VARCHAR(50) NOT NULL,
    model_alias VARCHAR(100),
    prompt_template_version VARCHAR(100),
    generation_metadata JSONB,
    analysis_result JSONB,
    user_feedback TEXT,
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (chapter_id, version_number)
);
```

## 9.3. story_memories

```sql
CREATE TABLE story_memories (
    id UUID PRIMARY KEY,
    story_id UUID NOT NULL,
    chapter_id UUID,
    memory_type VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB,
    embedding VECTOR(1536),
    importance_score NUMERIC(5, 4) DEFAULT 0.5,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 10. Redis key design

```text
ai:job:{jobId}:state
ai:job:{jobId}:stream
ai:story:{storyId}:context-cache
ai:story:{storyId}:generation-lock
ai:prompt:{promptHash}
ai:ratelimit:{tenantId}:{modelAlias}
```

Ví dụ:

```json
{
  "job_id": "job_01JXYZ",
  "status": "GENERATING",
  "progress": 55,
  "current_step": "LLM_WRITER",
  "updated_at": "2026-07-16T08:35:00+07:00"
}
```

TTL đề xuất:

```text
Job state: 24 giờ sau khi hoàn thành
Prompt cache: 30-60 phút
Context cache: 10-30 phút
Generation lock: 5-15 phút
```

---

## 11. Error response chuẩn

```json
{
  "code": 42201,
  "message": "Selected model does not support the required context length",
  "error": {
    "type": "MODEL_CAPABILITY_MISMATCH",
    "field": "model",
    "details": {
      "selected_model": "local-llama",
      "required_context_tokens": 82000,
      "supported_context_tokens": 32000
    }
  },
  "request_id": "req_01JXYZ",
  "timestamp": "2026-07-16T08:40:00+07:00"
}
```

HTTP status đề xuất:

```text
400 Bad Request          Request sai cấu trúc
401 Unauthorized         Service token không hợp lệ
403 Forbidden            Không có quyền truy cập story
404 Not Found            Story, chapter hoặc job không tồn tại
409 Conflict             Job đang chạy hoặc idempotency conflict
422 Unprocessable Entity Không đáp ứng constraint/model capability
429 Too Many Requests    Rate limit
500 Internal Error       Lỗi engine
502 Bad Gateway          Provider trả lỗi
503 Service Unavailable  Không có model khả dụng
504 Gateway Timeout      Provider timeout
```

---

## 12. Bảo mật

- Backend bên ngoài dùng service-to-service JWT hoặc API key có rotation.
- Không cho client truyền provider API key.
- Mã hóa secret bằng secret manager hoặc environment variable.
- Kiểm tra tenant ownership của story.
- Có rate limit theo tenant, user và model.
- Ghi audit log cho generate, regenerate, approve và publish.
- Không ghi toàn bộ prompt chứa dữ liệu nhạy cảm vào log thông thường.
- Có thể lưu prompt hash thay vì prompt thô.
- Loại bỏ dữ liệu nhạy cảm trước khi gửi tới provider nếu cần.

---

## 13. Observability

Mỗi request phải có:

```text
request_id
trace_id
job_id
story_id
chapter_id
model_alias
provider
prompt_template_version
input_tokens
output_tokens
latency_ms
revision_attempt
analysis_score
```

Metrics:

```text
ai_generation_total
ai_generation_success_total
ai_generation_failure_total
ai_generation_latency_seconds
ai_provider_error_total
ai_token_usage_total
ai_cost_estimate_total
ai_analysis_failure_total
ai_revision_attempt_total
```

---

## 14. Luồng hoàn chỉnh đề xuất

```text
1. Backend gọi POST /stories/{storyId}/chapters/generate.
2. API validate model alias, story ownership và request.
3. Tạo generation job và trả 202.
4. Worker gọi Planner.
5. Retriever lấy story context và vector memory.
6. Prompt Builder tạo prompt có version.
7. LLM Gateway chọn provider từ model alias.
8. LLM Writer sinh draft.
9. Story Analyzer kiểm tra draft.
10. Nếu lỗi context, quay lại Retriever.
11. Nếu lỗi plan, quay lại Planner.
12. Nếu lỗi writing, quay lại Prompt Builder.
13. Nếu đạt yêu cầu, lưu chapter version ở trạng thái READY_FOR_REVIEW.
14. User approve hoặc gửi feedback.
15. Khi approve, Memory Manager cập nhật summary, character state và embeddings.
16. Chapter chuyển sang APPROVED hoặc PUBLISHED.
```

---

## 15. Cấu trúc source code đề xuất

**Status: PROPOSED REFERENCE STRUCTURE.** Cây bên dưới mô tả hướng tổ chức, không khẳng định mọi module đã tồn tại.

**CURRENT repository roots:** `AI_engine/app`, `AI_engine/tests`, `API/static`, `API/tests`.

```text
app/
├── api/
│   └── v1/
│       ├── story_generation_router.py
│       ├── story_analysis_router.py
│       ├── job_router.py
│       └── model_router.py
├── application/
│   ├── commands/
│   ├── dto/
│   ├── orchestrators/
│   └── services/
├── domain/
│   ├── entities/
│   ├── enums/
│   ├── exceptions/
│   ├── ports/
│   └── value_objects/
├── infrastructure/
│   ├── db/
│   ├── redis/
│   ├── vector_store/
│   ├── llm/
│   │   ├── providers/
│   │   │   ├── anthropic_provider.py
│   │   │   ├── openai_provider.py
│   │   │   ├── gemini_provider.py
│   │   │   └── ollama_provider.py
│   │   ├── llm_gateway.py
│   │   ├── model_registry.py
│   │   └── provider_factory.py
│   └── storage/
├── pipeline/
│   ├── planner.py
│   ├── retriever.py
│   ├── prompt_builder.py
│   ├── writer.py
│   ├── analyzer.py
│   ├── issue_classifier.py
│   └── memory_manager.py
├── workers/
│   └── generation_worker.py
└── main.py
```

---

## 16. Khuyến nghị triển khai phiên bản đầu

MVP nên gồm:

1. Generate chapter bất đồng bộ.
2. Planner đơn giản.
3. Retriever lấy story bible và 3 chương gần nhất.
4. Hỗ trợ 2 model alias.
5. Story Analyzer kiểm tra continuity cơ bản.
6. Regenerate bằng feedback.
7. Approve và cập nhật memory.
8. Job status và SSE streaming.
9. PostgreSQL + pgvector.
10. Redis cho job state và lock.

Sau MVP mới bổ sung:

- Automatic model routing.
- Evidence-backed performance optimization: WP-00 policy áp dụng ngay; thay đổi hiệu năng chỉ được triển khai sau khi có baseline và bottleneck được đo.
- Multi-agent debate.
- Advanced reranking.
- Fine-tuned style model.
- Collaborative editing.
- Branching storyline.
- Automatic plot graph.

## 17. WP-00 — Engineering foundation

WP-00 governs how MVP-1 and later work packages are changed and verified. It does not replace the product or functional architecture described above.

- CURRENT describes repository facts verified by audit.
- PROPOSED describes selected design not yet implemented.
- DEFERRED describes work blocked on evidence or a separate decision.

Detailed rules:

- [WP-00 specification](docs/roadmap/WP-00_ENGINEERING_QUALITY_STANDARD.md)
- [Code quality](docs/engineering/code-quality.md)
- [Performance optimization](docs/engineering/performance.md)

Approval of documentation does not authorize dependency installation, formatting, refactoring, schema changes, CI or runtime changes.
