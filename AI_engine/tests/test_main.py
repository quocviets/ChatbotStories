import os
import sys
import json
import asyncio
import pytest
from datetime import UTC, datetime
from uuid import uuid4, UUID
from unittest.mock import MagicMock, AsyncMock
from fastapi.testclient import TestClient

# Mock Database structures
jobs_db = {}
versions_db = {}
memories_db = {}
chat_threads_db = {}
redis_queue = []

# Mock Postgres helpers
async def mock_init_postgres():
    pass

async def mock_close_postgres():
    pass

async def mock_save_job(job_id, tenant_id, user_id, story_id, operation, status, model_alias, idempotency_key, request_payload, max_attempts=3):
    # Idempotency check
    for j in jobs_db.values():
        if j["tenant_id"] == tenant_id and j["idempotency_key"] == idempotency_key:
            return j
    job = {
        "id": UUID(job_id),
        "tenant_id": tenant_id,
        "user_id": user_id,
        "story_id": UUID(story_id),
        "chapter_id": None,
        "operation": operation,
        "status": status,
        "current_step": None,
        "model_alias": model_alias,
        "progress": 0,
        "attempt": 0,
        "max_attempts": max_attempts,
        "idempotency_key": idempotency_key,
        "request_payload": request_payload,
        "result_payload": None,
        "error_payload": None,
        "created_at": datetime.now(UTC)
    }
    jobs_db[job_id] = job
    return job

async def mock_update_job(job_id, status, current_step=None, progress=None, attempt=None, result_payload=None, error_payload=None, chapter_id=None, started_at=None, completed_at=None):
    job = jobs_db.get(job_id)
    if job:
        active_statuses = ("QUEUED", "PLANNING", "RETRIEVING", "BUILDING_PROMPT", "GENERATING", "ANALYZING")
        if job["status"] == "CANCELLED" or (status == "CANCELLED" and job["status"] not in active_statuses):
            return None
        job["status"] = status
        if progress is not None:
            job["progress"] = progress
        if attempt is not None:
            job["attempt"] = attempt
        if status in ("COMPLETED", "FAILED", "CANCELLED", "NEEDS_MANUAL_REVIEW"):
            job["current_step"] = None
        elif current_step is not None:
            job["current_step"] = current_step
        if result_payload is not None:
            job["result_payload"] = result_payload
        if error_payload is not None:
            job["error_payload"] = error_payload
        if chapter_id is not None:
            job["chapter_id"] = UUID(chapter_id) if isinstance(chapter_id, str) else chapter_id
        return job
    return None

async def mock_get_job(job_id):
    return jobs_db.get(job_id)

async def mock_save_chapter_version(chapter_id, version_number, content, status, model_alias=None, prompt_template_version=None, generation_metadata=None, analysis_result=None, user_feedback=None, created_by="system"):
    key = (str(chapter_id), version_number)
    version_id = str(versions_db[key]["id"]) if key in versions_db else str(uuid4())
    version = {
        "id": UUID(version_id),
        "chapter_id": UUID(chapter_id) if isinstance(chapter_id, str) else chapter_id,
        "version_number": version_number,
        "content": content,
        "status": status,
        "model_alias": model_alias,
        "prompt_template_version": prompt_template_version,
        "generation_metadata": generation_metadata,
        "analysis_result": analysis_result,
        "user_feedback": user_feedback,
        "created_by": created_by,
        "created_at": datetime.now(UTC)
    }
    versions_db[key] = version
    return version

async def mock_get_latest_chapter_version(chapter_id):
    versions = [v for v in versions_db.values() if str(v["chapter_id"]) == str(chapter_id)]
    if versions:
        return max(versions, key=lambda x: x["version_number"])
    return None

async def mock_get_story_chapter(story_id, chapter_id):
    belongs_to_story = any(
        str(job["story_id"]) == str(story_id) and str(job["chapter_id"]) == str(chapter_id)
        for job in jobs_db.values()
    )
    return await mock_get_latest_chapter_version(chapter_id) if belongs_to_story else None

async def mock_get_chapter_version(chapter_id, version_number):
    return versions_db.get((str(chapter_id), version_number))

async def mock_get_chapter_version_by_id(version_id):
    for v in versions_db.values():
        if str(v["id"]) == str(version_id):
            return v
    return None

async def mock_get_chapter_versions(chapter_id):
    return [v for v in versions_db.values() if str(v["chapter_id"]) == str(chapter_id)]

async def mock_get_recent_chapters_content(story_id, limit=3):
    return []

async def mock_delete_chapter(story_id, chapter_id):
    return True

async def mock_rename_chapter(story_id, chapter_id, title):
    for job in jobs_db.values():
        if str(job.get("story_id")) == str(story_id) and str(job.get("chapter_id")) == str(chapter_id):
            job.setdefault("request_payload", {}).setdefault("chapter", {})["title"] = title
            return True
    return False

async def mock_save_chat_thread(story_id, thread_id, title, messages):
    thread = {
        "id": str(thread_id),
        "title": title,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "messages": [dict(message) for message in messages]
    }
    chat_threads_db[(str(story_id), str(thread_id))] = thread
    return thread

async def mock_append_chat_message(story_id, thread_id, title, role, content):
    key = (str(story_id), str(thread_id))
    thread = chat_threads_db.setdefault(key, {
        "id": str(thread_id),
        "title": title,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "messages": []
    })
    thread["title"] = title
    thread["updated_at"] = datetime.now(UTC)
    message = {"role": role, "content": content}
    thread["messages"].append(message)
    return message

async def mock_get_story_chat_threads(story_id):
    return [
        thread for (stored_story_id, _), thread in chat_threads_db.items()
        if stored_story_id == str(story_id)
    ]

async def mock_delete_chat_thread(story_id, thread_id):
    return chat_threads_db.pop((str(story_id), str(thread_id)), None) is not None

# Mock pgvector helpers
async def mock_save_memory_vector(story_id, chapter_id, memory_type, content, metadata=None, embedding=None, importance_score=0.5):
    memory_id = str(uuid4())
    memory = {
        "id": UUID(memory_id),
        "story_id": UUID(story_id) if isinstance(story_id, str) else story_id,
        "chapter_id": UUID(chapter_id) if chapter_id else None,
        "memory_type": memory_type,
        "content": content,
        "metadata": metadata,
        "importance_score": importance_score
    }
    memories_db[memory_id] = memory
    return memory

async def mock_search_memories_vector(story_id, query_embedding, limit=5):
    return list(memories_db.values())[:limit]

# Mock Redis class
class MockRedis:
    async def ping(self):
        return True
    async def rpush(self, queue_name, val):
        redis_queue.append(val)
        return 1
    async def blpop(self, queue_name, timeout=3.0):
        import asyncio
        if redis_queue:
            return (queue_name, redis_queue.pop(0))
        await asyncio.sleep(0.01)
        return None
    def pubsub(self):
        return MockPubSub()

class MockPubSub:
    async def subscribe(self, channel):
        pass
    async def listen(self):
        yield {"type": "message", "data": json.dumps({"event": "status", "data": {"status": "COMPLETED", "progress": 100}})}
    async def unsubscribe(self, channel):
        pass
    async def close(self):
        pass

# Overrides before importing app
import app.infrastructure.db.postgres_client as pg
import app.infrastructure.redis.redis_client as rd
import app.infrastructure.vector_store.pgvector_store as pgv

pg.init_postgres = AsyncMock(side_effect=mock_init_postgres)
pg.close_postgres = AsyncMock(side_effect=mock_close_postgres)
pg.save_job = AsyncMock(side_effect=mock_save_job)
pg.update_job = AsyncMock(side_effect=mock_update_job)
pg.get_job = AsyncMock(side_effect=mock_get_job)
pg.save_chapter_version = AsyncMock(side_effect=mock_save_chapter_version)
pg.get_latest_chapter_version = AsyncMock(side_effect=mock_get_latest_chapter_version)
pg.get_story_chapter = AsyncMock(side_effect=mock_get_story_chapter)
pg.get_chapter_version = AsyncMock(side_effect=mock_get_chapter_version)
pg.get_chapter_version_by_id = AsyncMock(side_effect=mock_get_chapter_version_by_id)
pg.get_chapter_versions = AsyncMock(side_effect=mock_get_chapter_versions)
pg.get_recent_chapters_content = AsyncMock(side_effect=mock_get_recent_chapters_content)
pg.delete_chapter = AsyncMock(side_effect=mock_delete_chapter)
pg.rename_chapter = AsyncMock(side_effect=mock_rename_chapter)
pg.save_chat_thread = AsyncMock(side_effect=mock_save_chat_thread)
pg.append_chat_message = AsyncMock(side_effect=mock_append_chat_message)
pg.get_story_chat_threads = AsyncMock(side_effect=mock_get_story_chat_threads)
pg.delete_chat_thread = AsyncMock(side_effect=mock_delete_chat_thread)

pgv.save_memory_vector = AsyncMock(side_effect=mock_save_memory_vector)
pgv.search_memories_vector = AsyncMock(side_effect=mock_search_memories_vector)

rd.init_redis = AsyncMock()
rd.close_redis = AsyncMock()
rd.get_redis = MagicMock(return_value=MockRedis())

from app.main import app

@pytest.fixture(scope="module", autouse=True)
def setup_database():
    yield


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_list_models(client):
    response = client.get("/api/v1/ai/models")
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert "data" in data
    assert len(data["data"]) > 0
    assert data["data"][0]["alias"] == "claude-sonnet"


def test_story_chat_is_separate_from_chapter_generation(client):
    from app.api.v1.story_generation_router import get_gateway
    from app.application.dto.story_dtos import LLMResponse

    story_id, thread_id = uuid4(), uuid4()
    gateway = MagicMock()
    gateway.generate = AsyncMock(return_value=LLMResponse(
        provider="test", model="test", content="Phản diện nên là người cố vấn."
    ))
    app.dependency_overrides[get_gateway] = lambda: gateway
    try:
        response = client.post(
            f"/api/v1/ai/stories/{story_id}/chat",
            json={
                "message": "Hãy phát triển nhân vật phản diện",
                "model": "claude-sonnet",
                "thread_id": str(thread_id),
                "thread_title": "Phát triển phản diện",
                "history": [{"role": "user", "content": "Phản diện phải gần gũi."}],
                "master_outline": "Một cuộc phản bội trong hoàng cung.",
                "master_tone": "Bí ẩn"
            }
        )
    finally:
        app.dependency_overrides.pop(get_gateway, None)

    assert response.status_code == 200
    assert response.json()["data"]["reply"] == "Phản diện nên là người cố vấn."
    assert gateway.generate.await_args.args[1].max_tokens == 3000
    assert [message["role"] for message in chat_threads_db[(str(story_id), str(thread_id))]["messages"]] == [
        "user", "assistant"
    ]
    loaded = client.get(f"/api/v1/ai/stories/{story_id}/chats")
    assert loaded.status_code == 200
    assert loaded.json()["data"][0]["title"] == "Phát triển phản diện"
    deleted = client.delete(f"/api/v1/ai/stories/{story_id}/chats/{thread_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True
    assert not jobs_db


def test_existing_local_chat_can_be_migrated(client):
    story_id, thread_id = uuid4(), uuid4()
    response = client.put(
        f"/api/v1/ai/stories/{story_id}/chats/{thread_id}",
        json={
            "title": "Chat cũ",
            "messages": [
                {"role": "user", "content": "Ý tưởng đã có trước khi lưu database."},
                {"role": "assistant", "content": "Tôi đã ghi nhận ý tưởng."}
            ]
        }
    )
    assert response.status_code == 200
    assert len(chat_threads_db[(str(story_id), str(thread_id))]["messages"]) == 2


def test_provider_error_is_returned_instead_of_fake_chat(client):
    from app.api.v1.story_generation_router import get_gateway
    from app.domain.exceptions.story_exceptions import ProviderException

    gateway = MagicMock()
    gateway.generate = AsyncMock(side_effect=ProviderException("Gemini TLS certificate failed"))
    app.dependency_overrides[get_gateway] = lambda: gateway
    try:
        response = client.post(
            f"/api/v1/ai/stories/{uuid4()}/chat",
            json={"message": "Hãy kiểm tra provider thật", "model": "gemini-long-context"}
        )
    finally:
        app.dependency_overrides.pop(get_gateway, None)

    assert response.status_code == 502
    assert response.json()["detail"] == "Gemini TLS certificate failed"


def test_gemini_retries_temporary_network_error(monkeypatch):
    from app.application.dto.story_dtos import LLMRequest
    from app.infrastructure.llm.providers import gemini_provider

    calls = 0

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "candidates": [{"content": {"parts": [{"text": "OK"}]}}],
                "usageMetadata": {}
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, *_args, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise gemini_provider.httpx.ConnectError("Temporary failure in name resolution")
            return FakeResponse()

    async def no_sleep(_delay):
        return None

    monkeypatch.setattr(gemini_provider.config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini_provider.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    monkeypatch.setattr(gemini_provider.asyncio, "sleep", no_sleep)

    response = asyncio.run(gemini_provider.GeminiProvider("test-model").generate(LLMRequest(
        model="test-model",
        system_prompt="test",
        messages=[{"role": "user", "content": "test"}]
    )))

    assert response.content == "OK"
    assert calls == 2


def test_delete_chapter(client):
    story_id, chapter_id = uuid4(), uuid4()
    response = client.delete(f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}")

    assert response.status_code == 200
    assert response.json()["data"]["deleted"] is True
    pg.delete_chapter.assert_awaited_with(str(story_id), str(chapter_id))


def test_rename_chapter(client):
    story_id, chapter_id = uuid4(), uuid4()
    job_key = "rename-chapter-job"
    jobs_db[job_key] = {
        "story_id": story_id,
        "chapter_id": chapter_id,
        "request_payload": {"chapter": {"title": "Tên cũ"}}
    }
    try:
        response = client.patch(
            f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}",
            json={"title": "Chương 1: Khởi đầu"}
        )
        assert response.status_code == 200
        assert jobs_db[job_key]["request_payload"]["chapter"]["title"] == "Chương 1: Khởi đầu"
    finally:
        jobs_db.pop(job_key, None)


def test_export_chat_message_as_chapter(client):
    story_id, thread_id = uuid4(), uuid4()
    response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/from-chat",
        headers={
            "Idempotency-Key": f"chat-{thread_id}-1",
            "X-Tenant-Id": "tenant-web",
            "X-User-Id": "user-web"
        },
        json={
            "title": "Chương 1",
            "content": "Nội dung đã được chốt nguyên văn từ câu trả lời của AI.",
            "model": "gemini-long-context",
            "thread_id": str(thread_id),
            "message_index": 1
        }
    )

    assert response.status_code == 201
    chapter = response.json()["data"]
    assert chapter["content"] == "Nội dung đã được chốt nguyên văn từ câu trả lời của AI."
    assert versions_db[(chapter["chapter_id"], 1)]["content"] == chapter["content"]
    assert any(
        job["operation"] == "CHAT_EXPORT"
        and str(job["story_id"]) == str(story_id)
        and str(job["chapter_id"]) == chapter["chapter_id"]
        for job in jobs_db.values()
    )


def test_read_chapter_only_from_its_story(client):
    story_id, chapter_id = uuid4(), uuid4()
    job_key = "read-chapter-job"
    version_key = (str(chapter_id), 1)
    jobs_db[job_key] = {
        "story_id": story_id,
        "chapter_id": chapter_id
    }
    version = {
        "id": uuid4(),
        "chapter_id": chapter_id,
        "version_number": 1,
        "content": "Nội dung chương cũ.",
        "status": "DRAFT",
        "model_alias": "claude-sonnet"
    }
    versions_db[version_key] = version

    try:
        response = client.get(f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}")
        assert response.status_code == 200
        assert response.json()["data"]["content"] == "Nội dung chương cũ."
        assert response.json()["data"]["status"] == "DRAFT"

        response = client.get(f"/api/v1/ai/stories/{uuid4()}/chapters/{chapter_id}")
        assert response.status_code == 404
    finally:
        jobs_db.pop(job_key, None)
        versions_db.pop(version_key, None)


def test_generate_chapter_async(client):
    story_id = str(uuid4())
    headers = {
        "Idempotency-Key": str(uuid4()),
        "X-Tenant-Id": "tenant_test_01",
        "X-User-Id": "user_test_01"
    }
    
    payload = {
        "request": "Viết chương tiếp theo về Minh đột nhập thư phòng mật tìm bức thư phản bội",
        "model": "claude-sonnet",
        "mode": "ASYNC",
        "chapter": {
            "title": "Bức thư trong bóng tối",
            "target_word_count": 500,
            "tone": "dark suspense"
        },
        "generation_config": {
            "temperature": 0.85,
            "max_output_tokens": 1000,
            "max_revision_attempts": 2,
            "auto_analyze": True
        },
        "constraints": [
            "Không được để Minh biết danh tính phản diện cuối cùng",
            "Kết thúc bằng cliffhanger"
        ]
    }
    
    response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/generate",
        headers=headers,
        json=payload
    )
    
    assert response.status_code == 202
    data = response.json()
    assert data["code"] == 202
    assert "job_id" in data["data"]
    assert data["data"]["status"] == "QUEUED"
    
    job_id = data["data"]["job_id"]
    
    # Verify we can fetch the job status
    status_response = client.get(f"/api/v1/ai/jobs/{job_id}")
    assert status_response.status_code == 200
    job_data = status_response.json()["data"]
    assert job_data["job_id"] == job_id
    assert job_data["status"] in ("QUEUED", "PLANNING", "RETRIEVING", "BUILDING_PROMPT", "GENERATING", "ANALYZING", "COMPLETED", "READY_FOR_REVIEW")


def test_generate_chapter_sync(client):
    story_id = str(uuid4())
    headers = {
        "Idempotency-Key": str(uuid4()),
        "X-Tenant-Id": "tenant_test_02",
        "X-User-Id": "user_test_02"
    }
    
    payload = {
        "request": "Minh tìm thấy lối thoát bí mật ra ngoài lâu đài cổ.",
        "model": "gpt-writing",
        "mode": "SYNC",
        "chapter": {
            "title": "Lối thoát",
            "target_word_count": 300,
            "tone": "action"
        },
        "generation_config": {
            "temperature": 0.7,
            "max_output_tokens": 1000,
            "max_revision_attempts": 1,
            "auto_analyze": True
        }
    }
    
    response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/generate-sync",
        headers=headers,
        json=payload
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert "chapter_id" in data["data"]
    assert "content" in data["data"]
    assert len(data["data"]["content"]) > 10
    assert "analysis" in data["data"]

    duplicate = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/generate-sync",
        headers=headers,
        json=payload
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["version_id"] == data["data"]["version_id"]
    
    chapter_id = data["data"]["chapter_id"]
    version_id = data["data"]["version_id"]
    
    # Test Approve Chapter
    approve_payload = {
        "version_id": version_id,
        "approved_by": "user_test_02",
        "update_memory": True
    }
    
    approve_response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}/approve",
        json=approve_payload
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["data"]["status"] == "APPROVED"
    assert approve_response.json()["data"]["memory_update_status"] == "COMPLETED"

    analyze_response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}/analyze",
        json={"version_id": version_id, "action": "REVISION_REQUESTED"}
    )
    assert analyze_response.status_code == 200
    assert "score" in analyze_response.json()["data"]

    lore_response = client.get(
        f"/api/v1/ai/stories/{story_id}/lore/search",
        params={"query": "sự kiện của chương", "limit": 5}
    )
    assert lore_response.status_code == 200
    assert lore_response.json()["data"]
    assert {"id", "chapter_id", "type", "content", "similarity"} <= lore_response.json()["data"][0].keys()
    
    # Test Continue Chapter
    continue_payload = {
        "request": "Viết tiếp cảnh Minh trèo tường trốn thoát và nghe thấy tiếng sói hú.",
        "model": "gpt-writing",
        "target_word_count": 300
    }
    
    continue_headers = {
        "X-Tenant-Id": "tenant_test_02",
        "X-User-Id": "user_test_02"
    }
    
    continue_response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}/continue",
        headers=continue_headers,
        json=continue_payload
    )
    assert continue_response.status_code == 200
    assert "content" in continue_response.json()["data"]
    assert len(continue_response.json()["data"]["content"]) > len(data["data"]["content"])
    
    # Test Feedback
    feedback_payload = {
        "version_id": continue_response.json()["data"]["version_id"],
        "action": "REVISION_REQUESTED",
        "feedback": "Hãy thay thế tiếng sói hú bằng tiếng dơi đập cánh."
    }
    feedback_response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}/feedback",
        headers=continue_headers,
        json=feedback_payload
    )
    assert feedback_response.status_code == 200
    assert feedback_response.json()["data"]["status"] == "REVISION_REQUESTED"

    payload["generation_config"]["auto_analyze"] = False
    headers["Idempotency-Key"] = str(uuid4())
    without_analysis = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/generate-sync", headers=headers, json=payload
    )
    assert without_analysis.status_code == 200
    assert without_analysis.json()["data"]["analysis"] is None


def test_invalid_or_cross_chapter_version_is_not_resolved():
    import asyncio
    from app.infrastructure.db.postgres_client import resolve_chapter_version

    chapter_id = str(uuid4())
    other_chapter_id = str(uuid4())
    version = asyncio.run(mock_save_chapter_version(other_chapter_id, 1, "other", "DRAFT"))

    assert asyncio.run(resolve_chapter_version(chapter_id, "not-a-version")) is None
    assert asyncio.run(resolve_chapter_version(chapter_id, str(version["id"]))) is None


def test_analyzer_invalid_json_fails_closed():
    import asyncio
    from app.application.dto.story_dtos import LLMResponse
    from app.pipeline.analyzer import StoryAnalyzer

    gateway = MagicMock()
    gateway.generate = AsyncMock(return_value=LLMResponse(provider="test", model="test", content="not-json"))
    result = asyncio.run(StoryAnalyzer(gateway).analyze("story", "draft", {}, {}))

    assert result.passed is False
    assert result.score == 0
    assert result.issues[0].severity == "HIGH"


def test_llm_fallbacks_do_not_cycle(monkeypatch):
    import asyncio
    import app.config as config
    from app.application.dto.story_dtos import LLMRequest
    from app.domain.exceptions.story_exceptions import ProviderException
    import app.infrastructure.llm.llm_gateway as gateway_module
    from app.infrastructure.llm.llm_gateway import LLMGateway

    calls = []

    class FailingProvider:
        async def generate(self, request):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(config, "OPENAI_API_KEY", "test")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(gateway_module, "_mock_mode_enabled", lambda: False)
    monkeypatch.setattr(
        gateway_module,
        "_get_provider",
        lambda alias: calls.append(alias) or FailingProvider()
    )
    request = LLMRequest(model="claude-sonnet", system_prompt="test", messages=[])

    with pytest.raises(ProviderException):
        asyncio.run(LLMGateway().generate("claude-sonnet", request))
    assert sorted(calls) == ["claude-sonnet", "gemini-long-context", "gpt-writing"]


def test_runtime_never_falls_back_to_mock(monkeypatch):
    import asyncio
    import app.config as config
    import app.infrastructure.llm.llm_gateway as gateway_module
    from app.application.dto.story_dtos import LLMRequest
    from app.domain.exceptions.story_exceptions import ProviderException

    monkeypatch.setattr(gateway_module, "_mock_mode_enabled", lambda: False)
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    gateway = gateway_module.LLMGateway()
    gateway._generate_mock = AsyncMock()
    request = LLMRequest(model="gpt-writing", system_prompt="test", messages=[])

    with pytest.raises(ProviderException, match="API key is not configured"):
        asyncio.run(gateway.generate("gpt-writing", request))
    with pytest.raises(ProviderException, match="OPENAI_API_KEY or GEMINI_API_KEY"):
        asyncio.run(gateway.get_embeddings("test"))
    gateway._generate_mock.assert_not_awaited()


def test_embeddings_use_gemini_when_openai_is_not_configured(monkeypatch):
    import app.config as config
    import app.infrastructure.llm.llm_gateway as gateway_module

    monkeypatch.setattr(gateway_module, "_mock_mode_enabled", lambda: False)
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gemini-test-key")
    get_embeddings = AsyncMock(return_value=[0.25] * 1536)
    monkeypatch.setattr(gateway_module.GeminiProvider, "get_embeddings", get_embeddings)

    result = asyncio.run(gateway_module.LLMGateway().get_embeddings("test"))

    assert len(result) == 1536
    get_embeddings.assert_awaited_once_with("test")


def test_terminal_job_stream_replays_completion(client):
    job_id = str(uuid4())
    story_id = str(uuid4())
    asyncio_job = __import__("asyncio").run(mock_save_job(
        job_id, "tenant", "user", story_id, "GENERATE", "COMPLETED",
        "gpt-writing", str(uuid4()), {}, 1
    ))
    asyncio_job["progress"] = 100
    asyncio_job["result_payload"] = {"chapter_id": "chapter", "content": "done"}

    response = client.get(f"/api/v1/ai/jobs/{job_id}/stream")
    assert response.status_code == 200
    assert "event: completed" in response.text
    assert '"content": "done"' in response.text

    missing = client.get(f"/api/v1/ai/jobs/{uuid4()}/stream")
    assert missing.status_code == 404


def test_job_stream_rechecks_terminal_state_after_subscribe(client, monkeypatch):
    import app.api.v1.job_router as job_router

    job_id, story_id = uuid4(), uuid4()
    initial = {
        "id": job_id,
        "story_id": story_id,
        "status": "GENERATING",
        "progress": 80,
        "result_payload": None
    }
    terminal = {
        **initial,
        "status": "COMPLETED",
        "progress": 100,
        "result_payload": {"chapter_id": "chapter-race", "content": "saved"}
    }

    class SilentPubSub:
        subscribed = False
        listened = False

        async def subscribe(self, _channel):
            self.subscribed = True

        async def listen(self):
            self.listened = True
            if False:
                yield None

        async def unsubscribe(self, _channel):
            return None

        async def close(self):
            return None

    pubsub = SilentPubSub()
    get_job_mock = AsyncMock(side_effect=[initial, terminal])
    monkeypatch.setattr(job_router, "get_job", get_job_mock)
    monkeypatch.setattr(job_router, "get_redis", lambda: MagicMock(pubsub=lambda: pubsub))

    response = client.get(f"/api/v1/ai/jobs/{job_id}/stream")

    assert response.status_code == 200
    assert "event: completed" in response.text
    assert '"content": "saved"' in response.text
    assert get_job_mock.await_count == 2
    assert pubsub.subscribed is True
    assert pubsub.listened is False


def test_cancel_does_not_overwrite_terminal_job():
    job_id, story_id = str(uuid4()), str(uuid4())
    job = asyncio.run(mock_save_job(
        job_id, "tenant", "user", story_id, "GENERATE", "COMPLETED",
        "gpt-writing", str(uuid4()), {}, 1
    ))

    cancelled = asyncio.run(mock_update_job(job_id, status="CANCELLED"))

    assert cancelled is None
    assert job["status"] == "COMPLETED"


def test_worker_recovers_from_temporary_redis_timeout(monkeypatch, caplog):
    from redis.exceptions import TimeoutError as RedisTimeoutError
    import app.workers.generation_worker as worker

    class TimeoutThenStopRedis:
        calls = 0

        async def blpop(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RedisTimeoutError("Timeout reading from localhost:6379")
            raise asyncio.CancelledError

    redis = TimeoutThenStopRedis()

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(worker, "get_redis", lambda: redis)
    monkeypatch.setattr(worker, "build_orchestrator", lambda _gateway: MagicMock())
    monkeypatch.setattr(worker.asyncio, "sleep", no_sleep)

    with caplog.at_level("WARNING", logger=worker.logger.name):
        asyncio.run(worker.worker_loop())

    assert redis.calls == 2
    assert "Redis queue temporarily unavailable" in caplog.text
    assert "Error in worker loop" not in caplog.text
