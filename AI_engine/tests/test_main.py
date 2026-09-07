import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

# Mock Database structures
jobs_db = {}
versions_db = {}
chapters_db = {}
memories_db = {}
chat_threads_db = {}
stories_db = {}
redis_queue = []


# Mock Postgres helpers
async def mock_init_postgres():
    pass


async def mock_close_postgres():
    pass


async def mock_save_job(
    job_id,
    tenant_id,
    user_id,
    story_id,
    operation,
    status,
    model_alias,
    idempotency_key,
    request_payload,
    max_attempts=3,
):
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
        "created_at": datetime.now(UTC),
    }
    jobs_db[job_id] = job
    return job


async def mock_update_job(
    job_id,
    status,
    current_step=None,
    progress=None,
    attempt=None,
    result_payload=None,
    error_payload=None,
    chapter_id=None,
    started_at=None,
    completed_at=None,
):
    job = jobs_db.get(job_id)
    if job:
        active_statuses = (
            "QUEUED",
            "PLANNING",
            "RETRIEVING",
            "BUILDING_PROMPT",
            "GENERATING",
            "ANALYZING",
        )
        if job["status"] == "CANCELLED" or (
            status == "CANCELLED" and job["status"] not in active_statuses
        ):
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


async def mock_save_chapter_version(
    chapter_id,
    version_number,
    content,
    status,
    model_alias=None,
    prompt_template_version=None,
    generation_metadata=None,
    analysis_result=None,
    user_feedback=None,
    created_by="system",
    story_id=None,
):
    chapter = chapters_db.get(str(chapter_id))
    if story_id is not None and (
        not chapter
        or str(chapter["story_id"]) != str(story_id)
        or chapter.get("deleted_at") is not None
    ):
        return None
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
        "created_at": datetime.now(UTC),
    }
    versions_db[key] = version
    return version


async def mock_create_story_chapter(
    story_id,
    chapter_id,
    title=None,
    source_thread_id=None,
    source_message_index=None,
    model_alias=None,
):
    existing = chapters_db.get(str(chapter_id))
    if existing:
        return existing
    allocated = [
        chapter["chapter_number"]
        for chapter in chapters_db.values()
        if str(chapter["story_id"]) == str(story_id)
    ]
    chapter_number = max(allocated, default=0) + 1
    if not title or (
        title.casefold().startswith("chương ") and title.split(maxsplit=1)[-1].isdigit()
    ):
        title = f"Chương {chapter_number}"
    chapter = {
        "id": UUID(chapter_id),
        "story_id": UUID(story_id),
        "chapter_number": chapter_number,
        "title": title,
        "status": "ACTIVE",
        "source_thread_id": source_thread_id,
        "source_message_index": source_message_index,
        "model_alias": model_alias,
        "deleted_at": None,
    }
    chapters_db[str(chapter_id)] = chapter
    return chapter


async def mock_attach_job_chapter(job_id, chapter_id):
    job = jobs_db.get(str(job_id))
    if not job or job["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
        return False
    job["chapter_id"] = UUID(chapter_id)
    return True


async def mock_list_story_chapters(story_id):
    result = []
    for chapter in chapters_db.values():
        if str(chapter["story_id"]) != str(story_id) or chapter.get("deleted_at"):
            continue
        version = await mock_get_latest_chapter_version(chapter["id"])
        if version:
            result.append(
                {
                    **version,
                    "chapter_number": chapter["chapter_number"],
                    "title": chapter["title"],
                    "source_thread_id": chapter.get("source_thread_id"),
                    "source_message_index": chapter.get("source_message_index"),
                    "chapter_model_alias": chapter.get("model_alias"),
                    "version_id": version["id"],
                }
            )
    return sorted(result, key=lambda item: item["chapter_number"], reverse=True)


async def mock_list_deleted_chapter_sources(story_id):
    return [
        {
            "chapter_id": chapter["id"],
            "source_thread_id": chapter["source_thread_id"],
            "source_message_index": chapter["source_message_index"],
        }
        for chapter in chapters_db.values()
        if (
            str(chapter["story_id"]) == str(story_id)
            and chapter.get("deleted_at") is not None
            and chapter.get("source_thread_id") is not None
            and chapter.get("source_message_index") is not None
        )
    ]


async def mock_save_next_chapter_version(story_id, chapter_id, **values):
    versions = await mock_get_chapter_versions(chapter_id)
    return await mock_save_chapter_version(
        chapter_id=chapter_id,
        story_id=story_id,
        version_number=max((version["version_number"] for version in versions), default=0) + 1,
        **values,
    )


async def mock_resolve_story_chapter_version(story_id, chapter_id, version_id_or_num):
    chapter = chapters_db.get(str(chapter_id))
    if (
        not chapter
        or str(chapter["story_id"]) != str(story_id)
        or chapter.get("deleted_at") is not None
    ):
        return None
    if str(version_id_or_num).isdigit():
        return await mock_get_chapter_version(chapter_id, int(version_id_or_num))
    version = await mock_get_chapter_version_by_id(version_id_or_num)
    return version if version and str(version["chapter_id"]) == str(chapter_id) else None


async def mock_get_latest_chapter_version(chapter_id):
    versions = [v for v in versions_db.values() if str(v["chapter_id"]) == str(chapter_id)]
    if versions:
        return max(versions, key=lambda x: x["version_number"])
    return None


async def mock_get_story_chapter(story_id, chapter_id):
    chapter = chapters_db.get(str(chapter_id))
    belongs_to_story = (
        chapter and str(chapter["story_id"]) == str(story_id) and chapter.get("deleted_at") is None
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
    chapter = chapters_db.get(str(chapter_id))
    if (
        not chapter
        or str(chapter["story_id"]) != str(story_id)
        or chapter.get("deleted_at") is not None
    ):
        return False
    chapter["deleted_at"] = datetime.now(UTC)
    chapter["status"] = "DELETED"
    for key in [key for key in versions_db if key[0] == str(chapter_id)]:
        del versions_db[key]
    for key in [
        key
        for key, job in jobs_db.items()
        if str(job["story_id"]) == str(story_id) and str(job.get("chapter_id")) == str(chapter_id)
    ]:
        del jobs_db[key]
    return True


async def mock_rename_chapter(story_id, chapter_id, title):
    chapter = chapters_db.get(str(chapter_id))
    if not chapter or str(chapter["story_id"]) != str(story_id) or chapter.get("deleted_at"):
        return False
    chapter["title"] = title
    for job in jobs_db.values():
        if str(job.get("story_id")) == str(story_id) and str(job.get("chapter_id")) == str(
            chapter_id
        ):
            job.setdefault("request_payload", {}).setdefault("chapter", {})["title"] = title
            break
    return True


async def mock_save_chat_thread(story_id, thread_id, title, messages):
    thread = {
        "id": str(thread_id),
        "title": title,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
        "messages": [dict(message) for message in messages],
    }
    chat_threads_db[(str(story_id), str(thread_id))] = thread
    return thread


async def mock_append_chat_message(story_id, thread_id, title, role, content):
    key = (str(story_id), str(thread_id))
    thread = chat_threads_db.setdefault(
        key,
        {
            "id": str(thread_id),
            "title": title,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
            "messages": [],
        },
    )
    thread["title"] = title
    thread["updated_at"] = datetime.now(UTC)
    message = {"role": role, "content": content}
    thread["messages"].append(message)
    return message


async def mock_get_story_chat_threads(story_id):
    return [
        thread
        for (stored_story_id, _), thread in chat_threads_db.items()
        if stored_story_id == str(story_id)
    ]


async def mock_delete_chat_thread(story_id, thread_id):
    return chat_threads_db.pop((str(story_id), str(thread_id)), None) is not None


async def mock_list_stories(tenant_id, user_id):
    stories = []
    for story in stories_db.values():
        if story["tenant_id"] != tenant_id or story["user_id"] != user_id:
            continue
        story_id = str(story["id"])
        stories.append(
            {
                **story,
                "chapter_count": sum(
                    1
                    for chapter in chapters_db.values()
                    if str(chapter["story_id"]) == story_id and not chapter.get("deleted_at")
                ),
                "chat_count": sum(
                    1 for stored_story_id, _ in chat_threads_db if stored_story_id == story_id
                ),
            }
        )
    return sorted(
        stories,
        key=lambda story: (
            story.get("archived_at") is not None,
            story["updated_at"],
        ),
        reverse=False,
    )


async def mock_create_story(tenant_id, user_id, title, master_tone="", master_outline=""):
    now = datetime.now(UTC)
    story_id = uuid4()
    story = {
        "id": story_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "title": title,
        "master_tone": master_tone,
        "master_outline": master_outline,
        "metadata_initialized": True,
        "created_at": now,
        "updated_at": now,
        "archived_at": None,
    }
    stories_db[str(story_id)] = story
    return story


async def mock_import_legacy_stories(tenant_id, user_id, stories):
    imported = 0
    for item in stories:
        key = str(item["id"])
        existing = stories_db.get(key)
        if existing and (
            existing["tenant_id"] != tenant_id
            or existing["user_id"] != user_id
            or existing["metadata_initialized"]
        ):
            continue
        now = datetime.now(UTC)
        stories_db[key] = {
            "id": UUID(key),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "title": item["title"],
            "master_tone": item.get("master_tone") or "",
            "master_outline": item.get("master_outline") or "",
            "metadata_initialized": True,
            "created_at": item.get("created_at") or now,
            "updated_at": now,
            "archived_at": item.get("archived_at"),
        }
        imported += 1
    return imported


async def mock_update_story(
    story_id,
    tenant_id,
    user_id,
    *,
    title=None,
    master_tone=None,
    master_outline=None,
    archived=None,
):
    story = stories_db.get(str(story_id))
    if not story or story["tenant_id"] != tenant_id or story["user_id"] != user_id:
        return None
    if title is not None:
        story["title"] = title
    if master_tone is not None:
        story["master_tone"] = master_tone
    if master_outline is not None:
        story["master_outline"] = master_outline
    if archived is not None:
        story["archived_at"] = datetime.now(UTC) if archived else None
    story["metadata_initialized"] = True
    story["updated_at"] = datetime.now(UTC)
    return story


# Mock pgvector helpers
async def mock_save_memory_vector(
    story_id, chapter_id, memory_type, content, metadata=None, embedding=None, importance_score=0.5
):
    memory_id = str(uuid4())
    memory = {
        "id": UUID(memory_id),
        "story_id": UUID(story_id) if isinstance(story_id, str) else story_id,
        "chapter_id": UUID(chapter_id) if chapter_id else None,
        "memory_type": memory_type,
        "content": content,
        "metadata": metadata,
        "importance_score": importance_score,
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

    # Match the Redis client API; this mock does not implement timeout handling itself.
    async def blpop(self, queue_name, timeout=3.0):  # noqa: ASYNC109
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
        yield {
            "type": "message",
            "data": json.dumps(
                {"event": "status", "data": {"status": "COMPLETED", "progress": 100}}
            ),
        }

    async def unsubscribe(self, channel):
        pass

    async def close(self):
        pass


# These imports intentionally precede app import so dependencies can be overridden first.
import app.infrastructure.db.postgres_client as pg  # noqa: E402
import app.infrastructure.redis.redis_client as rd  # noqa: E402
import app.infrastructure.vector_store.pgvector_store as pgv  # noqa: E402

real_get_recent_chapters_content = pg.get_recent_chapters_content

pg.init_postgres = AsyncMock(side_effect=mock_init_postgres)
pg.close_postgres = AsyncMock(side_effect=mock_close_postgres)
pg.save_job = AsyncMock(side_effect=mock_save_job)
pg.update_job = AsyncMock(side_effect=mock_update_job)
pg.get_job = AsyncMock(side_effect=mock_get_job)
pg.create_story_chapter = AsyncMock(side_effect=mock_create_story_chapter)
pg.attach_job_chapter = AsyncMock(side_effect=mock_attach_job_chapter)
pg.list_story_chapters = AsyncMock(side_effect=mock_list_story_chapters)
pg.list_deleted_chapter_sources = AsyncMock(side_effect=mock_list_deleted_chapter_sources)
pg.save_chapter_version = AsyncMock(side_effect=mock_save_chapter_version)
pg.save_next_chapter_version = AsyncMock(side_effect=mock_save_next_chapter_version)
pg.get_latest_chapter_version = AsyncMock(side_effect=mock_get_latest_chapter_version)
pg.get_story_chapter = AsyncMock(side_effect=mock_get_story_chapter)
pg.resolve_story_chapter_version = AsyncMock(side_effect=mock_resolve_story_chapter_version)
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
pg.list_stories = AsyncMock(side_effect=mock_list_stories)
pg.create_story = AsyncMock(side_effect=mock_create_story)
pg.import_legacy_stories = AsyncMock(side_effect=mock_import_legacy_stories)
pg.update_story = AsyncMock(side_effect=mock_update_story)

pgv.save_memory_vector = AsyncMock(side_effect=mock_save_memory_vector)
pgv.search_memories_vector = AsyncMock(side_effect=mock_search_memories_vector)

rd.init_redis = AsyncMock()
rd.close_redis = AsyncMock()
rd.get_redis = MagicMock(return_value=MockRedis())

from app.main import app  # noqa: E402


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
    assert response.headers["Permissions-Policy"] == "microphone=(self)"
    data = response.json()
    assert data["code"] == 200
    assert "data" in data
    assert len(data["data"]) > 0
    assert data["data"][0]["alias"] == "claude-sonnet"


def test_story_metadata_is_persisted_and_owner_scoped(client):
    headers = {"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a"}
    created = client.post(
        "/api/v1/ai/stories",
        headers=headers,
        json={
            "title": "Thiên hiệp",
            "master_tone": "Ngắn, lạnh",
            "master_outline": "Nhân vật tìm lại ký ức.",
        },
    )
    assert created.status_code == 201
    story = created.json()["data"]

    listed = client.get("/api/v1/ai/stories", headers=headers)
    assert listed.status_code == 200
    assert any(item["id"] == story["id"] for item in listed.json()["data"])

    archived = client.patch(
        f"/api/v1/ai/stories/{story['id']}",
        headers=headers,
        json={"archived": True},
    )
    assert archived.status_code == 200
    assert archived.json()["data"]["archived_at"] is not None

    other_owner = client.patch(
        f"/api/v1/ai/stories/{story['id']}",
        headers={"X-Tenant-Id": "tenant-a", "X-User-Id": "user-b"},
        json={"title": "Không được ghi đè"},
    )
    assert other_owner.status_code == 404
    assert stories_db[story["id"]]["title"] == "Thiên hiệp"


def test_legacy_story_metadata_can_only_initialize_once(client):
    story_id = str(uuid4())
    now = datetime.now(UTC)
    stories_db[story_id] = {
        "id": UUID(story_id),
        "tenant_id": "tenant-web",
        "user_id": "user-web",
        "title": "Truyện đã nhập",
        "master_tone": "",
        "master_outline": "",
        "metadata_initialized": False,
        "created_at": now,
        "updated_at": now,
        "archived_at": None,
    }
    headers = {"X-Tenant-Id": "tenant-web", "X-User-Id": "user-web"}
    payload = {
        "stories": [
            {
                "id": story_id,
                "title": "Tên từ workspace cũ",
                "master_tone": "Tự nhiên",
                "master_outline": "Đề cương cũ",
            }
        ]
    }

    first = client.post("/api/v1/ai/stories/import", headers=headers, json=payload)
    assert first.status_code == 200
    assert first.json()["data"]["imported"] == 1

    payload["stories"][0]["title"] = "Tên bị sửa trong localStorage"
    second = client.post("/api/v1/ai/stories/import", headers=headers, json=payload)
    assert second.status_code == 200
    assert second.json()["data"]["imported"] == 0
    assert stories_db[story_id]["title"] == "Tên từ workspace cũ"


def test_story_chat_is_separate_from_chapter_generation(client):
    from app.api.v1.story_generation_router import get_gateway
    from app.application.dto.story_dtos import LLMResponse

    story_id, thread_id = uuid4(), uuid4()
    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=LLMResponse(
            provider="test", model="test", content="Phản diện nên là người cố vấn."
        )
    )
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
                "master_tone": "Bí ẩn",
            },
        )
    finally:
        app.dependency_overrides.pop(get_gateway, None)

    assert response.status_code == 200
    assert response.json()["data"]["reply"] == "Phản diện nên là người cố vấn."
    assert gateway.generate.await_args.args[1].max_tokens == 3000
    assert [
        message["role"] for message in chat_threads_db[(str(story_id), str(thread_id))]["messages"]
    ] == ["user", "assistant"]
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
                {"role": "assistant", "content": "Tôi đã ghi nhận ý tưởng."},
            ],
        },
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
            json={"message": "Hãy kiểm tra provider thật", "model": "gemini-long-context"},
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
            return {"candidates": [{"content": {"parts": [{"text": "OK"}]}}], "usageMetadata": {}}

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

    response = asyncio.run(
        gemini_provider.GeminiProvider("test-model").generate(
            LLMRequest(
                model="test-model",
                system_prompt="test",
                messages=[{"role": "user", "content": "test"}],
            )
        )
    )

    assert response.content == "OK"
    assert calls == 2


def test_delete_chapter(client):
    story_id, chapter_id = uuid4(), uuid4()
    asyncio.run(mock_create_story_chapter(str(story_id), str(chapter_id)))
    response = client.delete(f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}")

    assert response.status_code == 200
    assert response.json()["data"]["deleted"] is True
    pg.delete_chapter.assert_awaited_with(str(story_id), str(chapter_id))


def test_rename_chapter(client):
    story_id, chapter_id = uuid4(), uuid4()
    asyncio.run(mock_create_story_chapter(str(story_id), str(chapter_id)))
    job_key = "rename-chapter-job"
    jobs_db[job_key] = {
        "story_id": story_id,
        "chapter_id": chapter_id,
        "request_payload": {"chapter": {"title": "Tên cũ"}},
    }
    try:
        response = client.patch(
            f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}",
            json={"title": "Chương 1: Khởi đầu"},
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
            "X-User-Id": "user-web",
        },
        json={
            "title": "Chương 1",
            "content": "Nội dung đã được chốt nguyên văn từ câu trả lời của AI.",
            "model": "gemini-long-context",
            "thread_id": str(thread_id),
            "message_index": 1,
        },
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


def test_story_chapter_numbers_are_server_allocated_and_not_reused_after_delete(client):
    story_id = uuid4()

    def export(message_index):
        thread_id = uuid4()
        return client.post(
            f"/api/v1/ai/stories/{story_id}/chapters/from-chat",
            headers={
                "Idempotency-Key": f"numbering-{thread_id}",
                "X-Tenant-Id": "tenant-web",
                "X-User-Id": "user-web",
            },
            json={
                "title": "Chương 1",
                "content": f"Nội dung chương thứ {message_index}.",
                "model": "gemini-long-context",
                "thread_id": str(thread_id),
                "message_index": message_index,
            },
        )

    first = export(1)
    second = export(2)
    assert first.status_code == second.status_code == 201
    second_id = second.json()["data"]["chapter_id"]
    assert (
        client.delete(f"/api/v1/ai/stories/{story_id}/chapters/{second_id}").json()["data"][
            "deleted"
        ]
        is True
    )

    third = export(3)
    assert third.status_code == 201
    listed = client.get(f"/api/v1/ai/stories/{story_id}/chapters")
    assert listed.status_code == 200
    assert [chapter["chapter_number"] for chapter in listed.json()["data"]] == [3, 1]
    assert listed.json()["deleted_sources"] == [
        {
            "chapter_id": second_id,
            "thread_id": str(chapters_db[second_id]["source_thread_id"]),
            "message_index": 2,
        }
    ]
    assert third.json()["data"]["title"] == "Chương 3"


def test_continue_cannot_cross_story_or_restore_a_deleted_chapter(client):
    from app.api.v1.story_generation_router import get_gateway
    from app.application.dto.story_dtos import LLMResponse

    story_id, other_story_id, chapter_id = uuid4(), uuid4(), uuid4()
    asyncio.run(mock_create_story_chapter(str(story_id), str(chapter_id)))
    asyncio.run(
        mock_save_chapter_version(
            str(chapter_id),
            1,
            "Bản chương đang tồn tại.",
            "READY_FOR_REVIEW",
        )
    )

    gateway = MagicMock()
    gateway.generate = AsyncMock()
    app.dependency_overrides[get_gateway] = lambda: gateway
    payload = {
        "request": "Viết tiếp cảnh kế tiếp.",
        "model": "gpt-writing",
        "target_word_count": 300,
    }
    try:
        wrong_story = client.post(
            f"/api/v1/ai/stories/{other_story_id}/chapters/{chapter_id}/continue",
            headers={"X-User-Id": "user-web"},
            json=payload,
        )
        assert wrong_story.status_code == 404
        gateway.generate.assert_not_awaited()

        async def delete_during_llm(*_args, **_kwargs):
            await mock_delete_chapter(str(story_id), str(chapter_id))
            return LLMResponse(
                provider="test",
                model="test",
                content="Phần viết tiếp không được phép hồi sinh chương.",
            )

        gateway.generate = AsyncMock(side_effect=delete_during_llm)
        raced = client.post(
            f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}/continue",
            headers={"X-User-Id": "user-web"},
            json=payload,
        )
        assert raced.status_code == 410
        assert asyncio.run(mock_get_latest_chapter_version(str(chapter_id))) is None
    finally:
        app.dependency_overrides.pop(get_gateway, None)


def test_read_chapter_only_from_its_story(client):
    story_id, chapter_id = uuid4(), uuid4()
    asyncio.run(mock_create_story_chapter(str(story_id), str(chapter_id)))
    job_key = "read-chapter-job"
    version_key = (str(chapter_id), 1)
    jobs_db[job_key] = {"story_id": story_id, "chapter_id": chapter_id}
    version = {
        "id": uuid4(),
        "chapter_id": chapter_id,
        "version_number": 1,
        "content": "Nội dung chương cũ.",
        "status": "DRAFT",
        "model_alias": "claude-sonnet",
        "generation_metadata": {
            "source": {
                "thread_id": "chat-source",
                "message_index": "4",
            }
        },
    }
    versions_db[version_key] = version

    try:
        response = client.get(f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}")
        assert response.status_code == 200
        assert response.json()["data"]["content"] == "Nội dung chương cũ."
        assert response.json()["data"]["status"] == "DRAFT"
        assert response.json()["data"]["thread_id"] == "chat-source"
        assert response.json()["data"]["message_index"] == "4"

        response = client.get(f"/api/v1/ai/stories/{uuid4()}/chapters/{chapter_id}")
        assert response.status_code == 404
    finally:
        jobs_db.pop(job_key, None)
        versions_db.pop(version_key, None)


def test_regenerate_receives_base_draft_and_preserves_chat_source(client):
    from app.api.v1.story_generation_router import (
        PromptBuilder,
        get_analyzer,
        get_gateway,
        get_retriever,
    )
    from app.application.dto.story_dtos import AnalysisResult, LLMResponse

    story_id, chapter_id, version_id = uuid4(), uuid4(), uuid4()
    asyncio.run(mock_create_story_chapter(str(story_id), str(chapter_id)))
    versions_db[(str(chapter_id), 1)] = {
        "id": version_id,
        "chapter_id": chapter_id,
        "version_number": 1,
        "content": "Bản nháp gốc cần sửa đúng chi tiết này.",
        "status": "READY_FOR_REVIEW",
        "model_alias": "gpt-writing",
        "generation_metadata": {"source": {"thread_id": "chat-source", "message_index": "3"}},
    }
    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=LLMResponse(
            provider="test",
            model="test",
            content="Bản nháp đã sửa.",
        )
    )
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value={})
    analyzer = MagicMock()
    analyzer.analyze = AsyncMock(return_value=AnalysisResult(passed=True, score=90, issues=[]))
    prompt_builder = MagicMock()
    prompt_builder.build = AsyncMock(return_value=("SYSTEM", "REVISION INSTRUCTION"))
    app.dependency_overrides[get_gateway] = lambda: gateway
    app.dependency_overrides[get_retriever] = lambda: retriever
    app.dependency_overrides[get_analyzer] = lambda: analyzer
    app.dependency_overrides[PromptBuilder] = lambda: prompt_builder
    try:
        response = client.post(
            f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}/regenerate",
            headers={
                "X-Tenant-Id": "tenant-web",
                "X-User-Id": "user-web",
            },
            json={
                "base_version_id": str(version_id),
                "feedback": "Giảm lời giải thích.",
                "model": "gpt-writing",
            },
        )
    finally:
        app.dependency_overrides.pop(get_gateway, None)
        app.dependency_overrides.pop(get_retriever, None)
        app.dependency_overrides.pop(get_analyzer, None)
        app.dependency_overrides.pop(PromptBuilder, None)

    assert response.status_code == 200
    request = gateway.generate.await_args.args[1]
    assert "Bản nháp gốc cần sửa đúng chi tiết này." in request.messages[0]["content"]
    assert versions_db[(str(chapter_id), 2)]["generation_metadata"]["source"] == {
        "thread_id": "chat-source",
        "message_index": "3",
    }


def test_generate_chapter_async(client):
    story_id = str(uuid4())
    headers = {
        "Idempotency-Key": str(uuid4()),
        "X-Tenant-Id": "tenant_test_01",
        "X-User-Id": "user_test_01",
    }

    payload = {
        "request": "Viết chương tiếp theo về Minh đột nhập thư phòng mật tìm bức thư phản bội",
        "model": "claude-sonnet",
        "mode": "ASYNC",
        "chapter": {
            "title": "Bức thư trong bóng tối",
            "target_word_count": 500,
            "tone": "dark suspense",
        },
        "generation_config": {
            "temperature": 0.85,
            "max_output_tokens": 1000,
            "max_revision_attempts": 2,
            "auto_analyze": True,
        },
        "constraints": [
            "Không được để Minh biết danh tính phản diện cuối cùng",
            "Kết thúc bằng cliffhanger",
        ],
    }

    response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/generate", headers=headers, json=payload
    )

    assert response.status_code == 202
    data = response.json()
    assert data["code"] == 202
    assert "job_id" in data["data"]
    assert data["data"]["status"] == "QUEUED"
    assert {"job_id", "story_id", "status", "model", "created_at", "status_url"} <= data[
        "data"
    ].keys()

    job_id = data["data"]["job_id"]

    # Verify we can fetch the job status
    status_response = client.get(f"/api/v1/ai/jobs/{job_id}")
    assert status_response.status_code == 200
    job_data = status_response.json()["data"]
    assert job_data["job_id"] == job_id
    assert job_data["status"] in (
        "QUEUED",
        "PLANNING",
        "RETRIEVING",
        "BUILDING_PROMPT",
        "GENERATING",
        "ANALYZING",
        "COMPLETED",
        "READY_FOR_REVIEW",
    )


def test_generate_chapter_sync(client, monkeypatch):
    import app.config as config

    monkeypatch.setattr(config, "LLM_MOCK_MODE", True)
    story_id = str(uuid4())
    headers = {
        "Idempotency-Key": str(uuid4()),
        "X-Tenant-Id": "tenant_test_02",
        "X-User-Id": "user_test_02",
    }

    payload = {
        "request": "Minh tìm thấy lối thoát bí mật ra ngoài lâu đài cổ.",
        "model": "gpt-writing",
        "mode": "SYNC",
        "chapter": {"title": "Lối thoát", "target_word_count": 300, "tone": "action"},
        "generation_config": {
            "temperature": 0.7,
            "max_output_tokens": 1000,
            "max_revision_attempts": 1,
            "auto_analyze": True,
        },
    }

    response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/generate-sync", headers=headers, json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert "chapter_id" in data["data"]
    assert "content" in data["data"]
    assert len(data["data"]["content"]) > 10
    assert "analysis" in data["data"]
    assert {"chapter_id", "version_id", "status", "title", "content", "analysis"} <= data[
        "data"
    ].keys()

    duplicate = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/generate-sync", headers=headers, json=payload
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["version_id"] == data["data"]["version_id"]

    chapter_id = data["data"]["chapter_id"]
    version_id = data["data"]["version_id"]

    # Test Approve Chapter
    approve_payload = {
        "version_id": version_id,
        "approved_by": "user_test_02",
        "update_memory": True,
    }

    approve_response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}/approve", json=approve_payload
    )
    assert approve_response.status_code == 200
    assert approve_response.json()["data"]["status"] == "APPROVED"
    assert approve_response.json()["data"]["memory_update_status"] == "COMPLETED"

    analyze_response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}/analyze",
        json={"version_id": version_id, "action": "REVISION_REQUESTED"},
    )
    assert analyze_response.status_code == 200
    assert "score" in analyze_response.json()["data"]

    lore_response = client.get(
        f"/api/v1/ai/stories/{story_id}/lore/search",
        params={"query": "sự kiện của chương", "limit": 5},
    )
    assert lore_response.status_code == 200
    assert lore_response.json()["data"]
    assert {"id", "chapter_id", "type", "content", "similarity"} <= lore_response.json()["data"][
        0
    ].keys()

    # Test Continue Chapter
    continue_payload = {
        "request": "Viết tiếp cảnh Minh trèo tường trốn thoát và nghe thấy tiếng sói hú.",
        "model": "gpt-writing",
        "target_word_count": 300,
    }

    continue_headers = {"X-Tenant-Id": "tenant_test_02", "X-User-Id": "user_test_02"}

    continue_response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}/continue",
        headers=continue_headers,
        json=continue_payload,
    )
    assert continue_response.status_code == 200
    assert "content" in continue_response.json()["data"]
    assert len(continue_response.json()["data"]["content"]) > len(data["data"]["content"])

    # Test Feedback
    feedback_payload = {
        "version_id": continue_response.json()["data"]["version_id"],
        "action": "REVISION_REQUESTED",
        "feedback": "Hãy thay thế tiếng sói hú bằng tiếng dơi đập cánh.",
    }
    feedback_response = client.post(
        f"/api/v1/ai/stories/{story_id}/chapters/{chapter_id}/feedback",
        headers=continue_headers,
        json=feedback_payload,
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


def test_analyzer_invalid_json_becomes_manual_review_warning():
    import asyncio

    from app.application.dto.story_dtos import LLMResponse
    from app.pipeline.analyzer import StoryAnalyzer

    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=LLMResponse(provider="test", model="test", content="not-json")
    )
    result = asyncio.run(StoryAnalyzer(gateway).analyze("story", "draft", {}, {}))

    assert result.passed is False
    assert result.score == 0
    assert result.blocking_issues == []
    assert result.warnings[0].type == "ANALYZER_UNAVAILABLE"
    assert result.primary_issue_type == "ANALYZER_UNAVAILABLE"
    assert result.needs_manual_review is True


def test_analyzer_timeout_becomes_manual_review_unavailable():
    from app.pipeline.analyzer import StoryAnalyzer

    gateway = MagicMock()
    gateway.generate = AsyncMock(side_effect=TimeoutError())

    result = asyncio.run(StoryAnalyzer(gateway).analyze("story", "usable raw draft", {}, {}))

    assert result.passed is False
    assert result.primary_issue_type == "ANALYZER_UNAVAILABLE"
    assert result.blocking_issues == []
    assert result.needs_manual_review is True


def test_analyzer_missing_passed_is_not_treated_as_passed():
    from app.application.dto.story_dtos import LLMResponse
    from app.pipeline.analyzer import StoryAnalyzer

    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=LLMResponse(
            provider="test",
            model="test",
            content=json.dumps({"score": 80, "issues": []}),
        )
    )

    result = asyncio.run(StoryAnalyzer(gateway).analyze("story", "usable raw draft", {}, {}))

    assert result.passed is False
    assert result.primary_issue_type == "ANALYZER_UNAVAILABLE"
    assert result.needs_manual_review is True


def test_analysis_result_preserves_validator_result_and_classifies_issues():
    from app.application.dto.story_dtos import AnalysisResult, Issue

    warning = AnalysisResult(
        passed=False,
        score=20,
        issues=[
            Issue(
                type="DIRECT_CONTINUITY_CONTRADICTION",
                severity="MEDIUM",
                description="Possible mismatch.",
            )
        ],
    )
    unknown = AnalysisResult(
        passed=False,
        score=0,
        issues=[
            Issue(
                type="SOMETHING_NEW",
                severity="HIGH",
                description="Unknown validator issue.",
            )
        ],
    )
    blocking = AnalysisResult(
        passed=True,
        score=99,
        issues=[
            Issue(
                type="CORE_WORLD_RULE_VIOLATION",
                severity="HIGH",
                description="A core rule was directly violated.",
            )
        ],
    )

    assert warning.passed is False
    assert warning.blocking_issues == []
    assert warning.warnings == warning.issues
    assert unknown.passed is False
    assert unknown.needs_manual_review is True
    assert unknown.blocking_issues == []
    assert blocking.passed is True
    assert blocking.blocking_issues == blocking.issues


def test_llm_fallbacks_do_not_cycle(monkeypatch):
    import asyncio

    import app.config as config
    import app.infrastructure.llm.llm_gateway as gateway_module
    from app.application.dto.story_dtos import LLMRequest
    from app.domain.exceptions.story_exceptions import ProviderException
    from app.infrastructure.llm.llm_gateway import LLMGateway

    calls = []

    class FailingProvider:
        async def generate(self, request):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(config, "OPENAI_API_KEY", "test")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(config, "LLM_MOCK_MODE", False)
    monkeypatch.setattr(
        gateway_module, "_get_provider", lambda alias: calls.append(alias) or FailingProvider()
    )
    request = LLMRequest(model="claude-sonnet", system_prompt="test", messages=[])

    with pytest.raises(ProviderException):
        asyncio.run(LLMGateway().generate("claude-sonnet", request))
    assert sorted(calls) == ["claude-sonnet", "gemini-long-context", "gpt-writing"]


def test_successful_provider_fallback_records_reason(monkeypatch):
    import app.config as config
    import app.infrastructure.llm.llm_gateway as gateway_module
    from app.application.dto.story_dtos import LLMRequest, LLMResponse

    class FailingProvider:
        async def generate(self, request):
            raise RuntimeError("primary unavailable")

    class WorkingProvider:
        async def generate(self, request):
            return LLMResponse(
                provider="openai",
                model="fallback-model",
                content="usable response",
            )

    monkeypatch.setattr(config, "LLM_MOCK_MODE", False)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "test")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test")
    monkeypatch.setattr(
        gateway_module,
        "_get_provider",
        lambda alias: FailingProvider() if alias == "claude-sonnet" else WorkingProvider(),
    )

    response = asyncio.run(
        gateway_module.LLMGateway().generate(
            "claude-sonnet",
            LLMRequest(model="claude-sonnet", system_prompt="test", messages=[]),
        )
    )

    assert response.content == "usable response"
    assert response.fallback_from == "claude-sonnet"
    assert response.fallback_reason == "primary unavailable"


def test_mock_mode_requires_explicit_config_even_under_pytest(monkeypatch):
    import asyncio

    import app.config as config
    import app.infrastructure.llm.llm_gateway as gateway_module
    from app.application.dto.story_dtos import LLMRequest
    from app.domain.exceptions.story_exceptions import ProviderException

    monkeypatch.setattr(config, "LLM_MOCK_MODE", False)
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

    monkeypatch.setattr(config, "LLM_MOCK_MODE", True)
    response = asyncio.run(
        gateway_module.LLMGateway().generate(
            "gpt-writing",
            LLMRequest(
                model="gpt-writing",
                system_prompt="writer",
                messages=[],
                metadata={"purpose": "chapter_writer", "target_word_count": 300},
            ),
        )
    )
    assert response.provider == "mock"


def test_explicit_mock_uses_production_structured_contracts(monkeypatch):
    import app.config as config
    from app.application.dto.story_dtos import (
        AnalysisResult,
        ChapterPlan,
        LLMRequest,
        NarrativeCritique,
        TargetedRevision,
    )
    from app.domain.exceptions.story_exceptions import ProviderException
    from app.infrastructure.llm.llm_gateway import LLMGateway

    monkeypatch.setattr(config, "LLM_MOCK_MODE", True)
    gateway = LLMGateway()

    async def generate(purpose, scenario="valid", **metadata):
        return await gateway.generate(
            "gpt-writing",
            LLMRequest(
                model="gpt-writing",
                system_prompt="contract test",
                messages=[],
                response_format="json_object",
                metadata={
                    "purpose": purpose,
                    "mock_scenario": scenario,
                    **metadata,
                },
            ),
        )

    plan = asyncio.run(generate("story_planning", target_word_count=300))
    assert ChapterPlan.model_validate_json(plan.content).required_scenes

    critique = asyncio.run(generate("narrative_critique", "narrative_issue"))
    assert NarrativeCritique.model_validate_json(critique.content).needs_revision

    revision = asyncio.run(
        generate(
            "targeted_revision",
            target_paragraph_ids=["p0002"],
        )
    )
    assert (
        TargetedRevision.model_validate_json(revision.content).revisions[0].paragraph_id == "p0002"
    )

    analysis_response = asyncio.run(generate("story_analysis", "analysis_failed"))
    analysis = AnalysisResult.model_validate_json(analysis_response.content)
    assert analysis.passed is False
    assert analysis.blocking_issues

    assert asyncio.run(generate("story_analysis", "malformed")).content == "not-json"
    assert asyncio.run(generate("story_analysis", "schema_error")).content == "{}"
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(generate("story_analysis", "timeout"))
    with pytest.raises(ProviderException):
        asyncio.run(generate("story_analysis", "provider_error"))


def test_embeddings_use_gemini_when_openai_is_not_configured(monkeypatch):
    import app.config as config
    import app.infrastructure.llm.llm_gateway as gateway_module

    monkeypatch.setattr(config, "LLM_MOCK_MODE", False)
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "gemini-test-key")
    get_embeddings = AsyncMock(return_value=[0.25] * 1536)
    monkeypatch.setattr(gateway_module.GeminiProvider, "get_embeddings", get_embeddings)

    result = asyncio.run(gateway_module.LLMGateway().get_embeddings("test"))

    assert len(result) == 1536
    get_embeddings.assert_awaited_once_with("test")


def test_streaming_usage_is_unknown_when_provider_has_no_usage(monkeypatch):
    import app.config as config
    import app.infrastructure.llm.llm_gateway as gateway_module
    from app.application.dto.story_dtos import LLMRequest

    class StreamingProvider:
        async def stream(self, request):
            yield "first "
            yield "second"

    monkeypatch.setattr(config, "LLM_MOCK_MODE", False)
    monkeypatch.setattr(config, "OPENAI_API_KEY", "test")
    monkeypatch.setattr(gateway_module, "_get_provider", lambda _alias: StreamingProvider())
    chunks = []

    response = asyncio.run(
        gateway_module.LLMGateway().generate(
            "gpt-writing",
            LLMRequest(model="gpt-writing", system_prompt="test", messages=[]),
            stream_handler=lambda chunk: _collect_chunk(chunks, chunk),
        )
    )

    assert response.content == "first second"
    assert response.usage.usage_available is False
    assert response.usage.input_tokens is None
    assert response.usage.output_tokens is None
    assert response.usage.total_tokens is None


def test_memory_manager_skips_malformed_json_without_fabricating_lore(
    monkeypatch,
):
    import app.pipeline.memory_manager as memory_module
    from app.application.dto.story_dtos import LLMResponse

    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=LLMResponse(
            provider="test",
            model="test",
            content="not-json",
        )
    )
    gateway.get_embeddings = AsyncMock()
    save_memory = AsyncMock()
    monkeypatch.setattr(memory_module, "save_memory_vector", save_memory)

    result = asyncio.run(
        memory_module.MemoryManager(gateway).update_memory_after_approval(
            story_id="story",
            chapter_id="chapter",
            chapter_content="Usable approved chapter.",
            version_number=1,
        )
    )

    assert result == {
        "status": "SKIPPED",
        "reason": "INVALID_RESPONSE",
        "summary": "",
        "new_facts": [],
        "character_updates": [],
    }
    gateway.get_embeddings.assert_not_awaited()
    save_memory.assert_not_awaited()


async def _collect_chunk(chunks, chunk):
    chunks.append(chunk)


def test_terminal_job_stream_replays_completion(client):
    job_id = str(uuid4())
    story_id = str(uuid4())
    asyncio_job = __import__("asyncio").run(
        mock_save_job(
            job_id,
            "tenant",
            "user",
            story_id,
            "GENERATE",
            "COMPLETED",
            "gpt-writing",
            str(uuid4()),
            {},
            1,
        )
    )
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
        "result_payload": None,
    }
    terminal = {
        **initial,
        "status": "COMPLETED",
        "progress": 100,
        "result_payload": {"chapter_id": "chapter-race", "content": "saved"},
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
    job = asyncio.run(
        mock_save_job(
            job_id,
            "tenant",
            "user",
            story_id,
            "GENERATE",
            "COMPLETED",
            "gpt-writing",
            str(uuid4()),
            {},
            1,
        )
    )

    cancelled = asyncio.run(mock_update_job(job_id, status="CANCELLED"))

    assert cancelled is None
    assert job["status"] == "COMPLETED"


def test_worker_recovers_from_temporary_redis_timeout(monkeypatch, caplog):
    import app.workers.generation_worker as worker
    from redis.exceptions import TimeoutError as RedisTimeoutError

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


def test_recent_chapters_query_returns_one_preferred_version_per_chapter(monkeypatch):
    chapter_a, chapter_b = uuid4(), uuid4()
    candidates = [
        {"chapter_id": chapter_a, "version_number": 1, "status": "APPROVED"},
        {"chapter_id": chapter_a, "version_number": 2, "status": "APPROVED"},
        {"chapter_id": chapter_b, "version_number": 2, "status": "APPROVED"},
        {"chapter_id": chapter_b, "version_number": 1, "status": "PUBLISHED"},
    ]

    class FakeConnection:
        async def fetch(self, query, _story_id, limit):
            normalized = " ".join(query.split())
            assert "JOIN LATERAL" in normalized
            assert "cv.chapter_id = sc.id" in normalized
            assert "CASE cv.status WHEN 'PUBLISHED' THEN 0 ELSE 1 END" in normalized
            assert "cv.version_number DESC" in normalized
            assert "LIMIT 1" in normalized
            assert "sc.deleted_at IS NULL" in normalized
            assert "ORDER BY sc.chapter_number DESC" in normalized

            selected = []
            for chapter_id in (chapter_b, chapter_a):
                versions = [row for row in candidates if row["chapter_id"] == chapter_id]
                versions.sort(
                    key=lambda row: (
                        row["status"] != "PUBLISHED",
                        -row["version_number"],
                    )
                )
                selected.append(versions[0])
            return selected[:limit]

    class Acquire:
        async def __aenter__(self):
            return FakeConnection()

        async def __aexit__(self, *_args):
            return None

    class FakePool:
        def acquire(self):
            return Acquire()

    monkeypatch.setattr(pg, "get_db_pool", lambda: FakePool())

    result = asyncio.run(real_get_recent_chapters_content(str(uuid4()), limit=3))

    assert [(row["chapter_id"], row["version_number"], row["status"]) for row in result] == [
        (chapter_b, 1, "PUBLISHED"),
        (chapter_a, 2, "APPROVED"),
    ]


def test_retriever_classifies_context_without_repeating_memories(monkeypatch):
    import app.pipeline.retriever as retriever_module
    from app.application.commands.story_commands import GenerateChapterCommand
    from app.application.dto.story_dtos import ChapterOptions, GenerationConfig
    from app.pipeline.retriever import StoryRetriever

    memories = [
        {"memory_type": "NEW_FACT", "content": "Minh bị thương tay trái."},
        {"memory_type": "SUMMARY", "content": "Minh đã rời khỏi thành."},
        {"memory_type": "CHARACTER_STATE", "content": "Lan không còn tin Minh."},
        {"memory_type": "WORLD_RULE", "content": "Phép dịch chuyển cần vật dẫn."},
        {"memory_type": "PLOT_THREAD", "content": "Bức thư vẫn chưa được mở."},
    ]
    monkeypatch.setattr(
        retriever_module,
        "get_recent_chapters_content",
        AsyncMock(return_value=[{"version_number": 2, "content": "Đoạn văn chương trước."}]),
    )
    monkeypatch.setattr(
        retriever_module,
        "search_memories_vector",
        AsyncMock(return_value=memories),
    )
    gateway = MagicMock()
    gateway.get_embeddings = AsyncMock(return_value=[0.0])
    command = GenerateChapterCommand(
        story_id=str(uuid4()),
        tenant_id="tenant",
        user_id="user",
        idempotency_key=str(uuid4()),
        request="Viết tiếp cuộc truy đuổi",
        model="gpt-writing",
        mode="SYNC",
        chapter=ChapterOptions(),
        generation_config=GenerationConfig(),
        constraints=["Minh vẫn bị thương tay trái."],
        metadata={},
    )
    plan = {
        "required_scenes": [{"mandatory_facts": ["Bức thư còn nguyên niêm phong."]}],
        "continuity_constraints": ["Không đổi thời điểm sang ban ngày."],
    }

    context = asyncio.run(StoryRetriever(gateway).retrieve(command.story_id, command, plan))

    expected_groups = {
        "must_preserve_facts",
        "continuity_only",
        "recent_prose_reference",
        "character_state",
        "world_constraints",
        "relevant_memories",
    }
    assert expected_groups <= context.keys()
    assert expected_groups <= context["purposes"].keys()
    assert "Minh bị thương tay trái." in context["must_preserve_facts"]
    assert "Minh đã rời khỏi thành." in context["continuity_only"]
    assert context["character_state"] == ["Lan không còn tin Minh."]
    assert context["world_constraints"] == ["Phép dịch chuyển cần vật dẫn."]
    assert context["relevant_memories"] == ["Bức thư vẫn chưa được mở."]

    classified = (
        context["must_preserve_facts"]
        + context["continuity_only"]
        + context["character_state"]
        + context["world_constraints"]
        + context["relevant_memories"]
    )
    assert len(classified) == len(set(classified))


def test_planner_normalizes_scene_schema_and_drops_analysis_fields():
    from app.application.commands.story_commands import GenerateChapterCommand
    from app.application.dto.story_dtos import ChapterOptions, GenerationConfig, LLMResponse
    from app.pipeline.planner import StoryPlanner

    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=LLMResponse(
            provider="test",
            model="test",
            content=json.dumps(
                {
                    "chapter_goal": "Minh tìm lối thoát",
                    "chapter_type": "suspense",
                    "target_word_count": 1000,
                    "pov_character": "Minh",
                    "tone": "căng thẳng",
                    "required_scenes": [
                        {
                            "scene_id": "scene_1",
                            "objective": "Tìm cửa bí mật",
                            "conflict": "Lính gác đang đến",
                            "participants": ["Minh"],
                            "location": "Thư phòng",
                            "mandatory_facts": ["Minh bị thương tay trái"],
                            "state_before": ["Cửa đang đóng"],
                            "state_after": ["Minh tìm thấy ổ khóa"],
                            "forbidden_changes": ["Không chữa lành vết thương"],
                            "sample_dialogue": "Ta phải đi ngay",
                            "psychological_analysis": "Một đoạn phân tích dài không thuộc scene schema",
                        }
                    ],
                    "continuity_constraints": [],
                    "ending_hook": "Có tiếng bước chân",
                    "moral_conclusion": "Niềm tin luôn chiến thắng",
                },
                ensure_ascii=False,
            ),
        )
    )
    command = GenerateChapterCommand(
        story_id=str(uuid4()),
        tenant_id="tenant",
        user_id="user",
        idempotency_key=str(uuid4()),
        request="Viết chương Minh tìm lối thoát",
        model="gpt-writing",
        mode="SYNC",
        chapter=ChapterOptions(target_word_count=1000),
        generation_config=GenerationConfig(),
        constraints=[],
        metadata={},
    )

    plan = asyncio.run(StoryPlanner(gateway).create_plan(command, [], []))

    assert set(plan["required_scenes"][0]) == {
        "scene_id",
        "objective",
        "conflict",
        "participants",
        "location",
        "mandatory_facts",
        "state_before",
        "state_after",
        "forbidden_changes",
    }
    assert "moral_conclusion" not in plan


def test_prompt_separates_context_and_supports_optional_character_voice():
    from app.application.commands.story_commands import GenerateChapterCommand
    from app.application.dto.story_dtos import ChapterOptions, GenerationConfig
    from app.pipeline.prompt_builder import PromptBuilder

    legacy_options = ChapterOptions(
        character_wiki={
            "Lan": {"status": "Đang sống", "role": "trinh sát"},
        }
    )
    assert legacy_options.character_wiki["Lan"].speech_rhythm is None
    assert (
        ChapterOptions(character_wiki={"Ghi chú cũ": "chưa cấu trúc"}).character_wiki["Ghi chú cũ"]
        == "chưa cấu trúc"
    )

    command = GenerateChapterCommand(
        story_id=str(uuid4()),
        tenant_id="tenant",
        user_id="user",
        idempotency_key=str(uuid4()),
        request="Viết cảnh Minh và Lan trốn khỏi thành",
        model="gpt-writing",
        mode="SYNC",
        chapter=ChapterOptions(
            character_wiki={
                "Minh": {
                    "status": "Đang sống",
                    "role": "kiếm sĩ",
                    "speech_rhythm": "ngắn, trực diện",
                    "word_choice": "thô, phản ứng nhanh",
                    "conflict_style": "phản bác ngay",
                    "emotional_leak": "im lặng khi lo lắng",
                    "avoids": ["phân tích dài", "lời thoại triết lý"],
                },
            }
        ),
        generation_config=GenerationConfig(),
        constraints=[],
        metadata={},
    )
    plan = {
        "chapter_goal": "Rời khỏi thành",
        "chapter_type": "escape",
        "target_word_count": 1000,
        "pov_character": "Minh",
        "tone": "gấp gáp",
        "required_scenes": [
            {
                "scene_id": "scene_1",
                "objective": "Qua cổng thành",
                "conflict": "Lính canh kiểm tra",
                "participants": ["Minh", "Lan"],
                "location": "Cổng thành",
                "mandatory_facts": [],
                "state_before": [],
                "state_after": [],
                "forbidden_changes": [],
            }
        ],
        "ending_hook": "",
    }
    context = {
        "must_preserve_facts": ["Minh bị thương tay trái."],
        "continuity_only": ["Đêm trước trời có mưa."],
        "recent_prose_reference": [{"version_number": 1, "content": "Minh khép cửa."}],
        "character_state": ["Lan đang mất niềm tin."],
        "world_constraints": ["Không thể dịch chuyển tức thời."],
        "relevant_memories": ["Lính canh đã gặp Minh trước đó."],
    }

    system_prompt, user_prompt = asyncio.run(PromptBuilder().build(command, plan, context))

    for section in (
        "[1. WRITING TASK]",
        "[2. POINT OF VIEW AND TONE]",
        "[3. CHARACTER VOICE]",
        "[4. SCENE PLAN]",
        "[5. MUST PRESERVE]",
        "[6. CONTINUITY ONLY]",
        "[7. RECENT PROSE REFERENCE]",
        "[8. FORBIDDEN CHANGES]",
        "[9. OUTPUT REQUIREMENTS]",
    ):
        assert section in user_prompt
    assert "không phải nội dung bắt buộc phải nhắc lại" in user_prompt
    assert "ngắn, trực diện" in user_prompt
    assert "phân tích dài" in user_prompt
    assert "không dùng Markdown" in user_prompt
    assert "*, ** hay #" in user_prompt
    assert "Không giải thích lại điều hành động đã thể hiện" in system_prompt


def test_narrative_critique_schema_is_strict():
    from app.application.dto.story_dtos import NarrativeCritique
    from pydantic import ValidationError

    valid = {
        "needs_revision": True,
        "issues": [
            {
                "type": "authorial_conclusion",
                "severity": "medium",
                "paragraph_ids": ["p0002"],
                "evidence": "Họ hiểu rằng mọi chuyện đã thay đổi.",
                "reason": "Người kể kết luận lại điều cảnh đã thể hiện.",
                "revision_instruction": "Bỏ câu kết luận, giữ hành động.",
                "must_preserve": ["Minh vẫn bị thương tay trái."],
            }
        ],
    }
    assert NarrativeCritique.model_validate(valid).issues[0].paragraph_ids == ["p0002"]
    assert (
        NarrativeCritique.model_validate(
            {
                **valid,
                "issues": [{**valid["issues"][0], "type": "purple_prose"}],
            }
        )
        .issues[0]
        .type
        == "purple_prose"
    )

    with pytest.raises(ValidationError):
        NarrativeCritique.model_validate(
            {
                **valid,
                "unexpected": "field ngoài schema",
            }
        )
    with pytest.raises(ValidationError):
        NarrativeCritique.model_validate(
            {
                **valid,
                "issues": [{**valid["issues"][0], "type": "unknown_style_issue"}],
            }
        )


def test_narrative_critic_invalid_json_falls_back_without_revision():
    from app.application.dto.story_dtos import LLMResponse
    from app.pipeline.narrative_editor import NarrativeEditor

    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=LLMResponse(provider="test", model="test", content="not-json")
    )

    critique = asyncio.run(NarrativeEditor(gateway).critique("Một đoạn văn hợp lệ.", {}, None))

    assert critique.needs_revision is False
    assert critique.issues == []
    assert critique.fallback_reason


def test_targeted_revision_changes_only_marked_paragraph_once():
    from app.application.dto.story_dtos import LLMResponse
    from app.pipeline.narrative_editor import NarrativeEditor

    draft = (
        "Minh đặt bức thư lên bàn.\n\n"
        "Hắn nhận ra rằng sự phản bội này đã thay đổi tất cả.\n\n"
        "Ngoài cửa, tiếng chân dừng lại."
    )
    critique_json = {
        "needs_revision": True,
        "issues": [
            {
                "type": "authorial_conclusion",
                "severity": "medium",
                "paragraph_ids": ["p0002"],
                "evidence": "Hắn nhận ra rằng...",
                "reason": "Kết luận trực tiếp điều hành động đã thể hiện.",
                "revision_instruction": "Bỏ lời kết luận, giữ phản ứng.",
                "must_preserve": ["sự phản bội"],
            }
        ],
    }
    revision_json = {
        "revisions": [
            {
                "paragraph_id": "p0002",
                "revised_text": "Hắn nhìn bức thư hồi lâu. Hai chữ “sự phản bội” nhòe dưới đầu ngón tay.",
            }
        ],
    }
    gateway = MagicMock()
    gateway.generate = AsyncMock(
        side_effect=[
            LLMResponse(
                provider="test",
                model="critic",
                content=json.dumps(critique_json, ensure_ascii=False),
            ),
            LLMResponse(
                provider="test",
                model="writer",
                content=json.dumps(revision_json, ensure_ascii=False),
            ),
        ]
    )
    editor = NarrativeEditor(gateway)

    critique = asyncio.run(
        editor.critique(
            draft,
            {
                "must_preserve_facts": ["Minh vẫn bị thương tay trái."],
            },
            None,
        )
    )
    revised, applied = asyncio.run(
        editor.revise(
            draft=draft,
            critique=critique,
            context={"must_preserve_facts": ["Minh vẫn bị thương tay trái."]},
            plan={"pov_character": "Minh"},
            character_wiki=None,
            model_alias="gpt-writing",
        )
    )

    assert applied is True
    assert revised.startswith("Minh đặt bức thư lên bàn.\n\n")
    assert revised.endswith("\n\nNgoài cửa, tiếng chân dừng lại.")
    assert "Hắn nhận ra rằng" not in revised
    assert gateway.generate.await_count == 2


def test_targeted_revision_returns_raw_draft_on_invalid_response():
    from app.application.dto.story_dtos import LLMResponse, NarrativeCritique
    from app.pipeline.narrative_editor import NarrativeEditor

    draft = "Đoạn đầu.\n\nĐoạn cần sửa."
    critique = NarrativeCritique.model_validate(
        {
            "needs_revision": True,
            "issues": [
                {
                    "type": "summary_like_prose",
                    "severity": "high",
                    "paragraph_ids": ["p0002"],
                    "evidence": "Đoạn cần sửa.",
                    "reason": "Đang tóm tắt thay vì kể cảnh.",
                    "revision_instruction": "Viết lại riêng đoạn này.",
                    "must_preserve": [],
                }
            ],
        }
    )
    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=LLMResponse(
            provider="test",
            model="writer",
            content=json.dumps(
                {
                    "revisions": [{"paragraph_id": "p9999", "revised_text": "Sai ID."}],
                }
            ),
        )
    )

    revised, applied = asyncio.run(
        NarrativeEditor(gateway).revise(draft, critique, {}, {}, None, "gpt-writing")
    )

    assert revised == draft
    assert applied is False
    gateway.generate.assert_awaited_once()


def test_targeted_revision_cannot_remove_marked_mandatory_fact():
    from app.application.dto.story_dtos import LLMResponse, NarrativeCritique
    from app.pipeline.narrative_editor import NarrativeEditor

    draft = "Minh đặt kiếm Huyền Thiết xuống bàn."
    critique = NarrativeCritique.model_validate(
        {
            "needs_revision": True,
            "issues": [
                {
                    "type": "redundant_explanation",
                    "severity": "medium",
                    "paragraph_ids": ["p0001"],
                    "evidence": draft,
                    "reason": "Câu có phần giải thích thừa.",
                    "revision_instruction": "Rút gọn nhưng giữ vật phẩm.",
                    "must_preserve": ["Huyền Thiết"],
                }
            ],
        }
    )
    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=LLMResponse(
            provider="test",
            model="writer",
            content=json.dumps(
                {
                    "revisions": [
                        {
                            "paragraph_id": "p0001",
                            "revised_text": "Minh đặt thanh kiếm xuống bàn.",
                        }
                    ],
                }
            ),
        )
    )

    revised, applied = asyncio.run(
        NarrativeEditor(gateway).revise(draft, critique, {}, {}, None, "gpt-writing")
    )

    assert revised == draft
    assert applied is False


def test_targeted_revision_cannot_remove_context_mandatory_fact():
    from app.application.dto.story_dtos import LLMResponse, NarrativeCritique
    from app.pipeline.narrative_editor import NarrativeEditor

    draft = "Minh giữ Huyền Thiết trong tay."
    critique = NarrativeCritique.model_validate(
        {
            "needs_revision": True,
            "issues": [
                {
                    "type": "redundant_explanation",
                    "severity": "medium",
                    "paragraph_ids": ["p0001"],
                    "evidence": draft,
                    "reason": "The sentence contains redundant narration.",
                    "revision_instruction": "Shorten the sentence.",
                    "must_preserve": [],
                }
            ],
        }
    )
    gateway = MagicMock()
    gateway.generate = AsyncMock(
        return_value=LLMResponse(
            provider="test",
            model="writer",
            content=json.dumps(
                {
                    "revisions": [
                        {
                            "paragraph_id": "p0001",
                            "revised_text": "Minh giữ thanh kiếm trong tay.",
                        }
                    ],
                }
            ),
        )
    )

    revised, applied = asyncio.run(
        NarrativeEditor(gateway).revise(
            draft,
            critique,
            {"must_preserve_facts": ["Huyền Thiết"]},
            {},
            None,
            "gpt-writing",
        )
    )

    assert revised == draft
    assert applied is False


def test_low_severity_narrative_issue_does_not_trigger_revision():
    from app.application.dto.story_dtos import NarrativeCritique
    from app.pipeline.narrative_editor import NarrativeEditor

    critique = NarrativeCritique.model_validate(
        {
            "needs_revision": True,
            "issues": [
                {
                    "type": "pacing_drag",
                    "severity": "low",
                    "paragraph_ids": ["p0001"],
                    "evidence": "Đoạn hơi chậm.",
                    "reason": "Nhịp có thể gọn hơn.",
                    "revision_instruction": "Rút nhẹ.",
                    "must_preserve": [],
                }
            ],
        }
    )

    assert NarrativeEditor.has_revisable_issues(critique) is False


def test_targeted_revision_respects_paragraph_and_word_delta_limits(monkeypatch):
    import app.config as config
    from app.application.dto.story_dtos import (
        LLMResponse,
        NarrativeCritique,
    )
    from app.pipeline.narrative_editor import NarrativeEditor

    draft = "Alpha.\n\nBravo.\n\nCharlie."
    critique = NarrativeCritique.model_validate(
        {
            "needs_revision": True,
            "issues": [
                {
                    "type": "purple_prose",
                    "severity": "medium",
                    "paragraph_ids": ["p0001", "p0002"],
                    "evidence": "Alpha. Bravo.",
                    "reason": "Too ornate.",
                    "revision_instruction": "Shorten.",
                    "must_preserve": [],
                }
            ],
        }
    )
    gateway = MagicMock()
    gateway.generate = AsyncMock(
        side_effect=[
            LLMResponse(
                provider="test",
                model="test",
                content=json.dumps(
                    {
                        "revisions": [{"paragraph_id": "p0001", "revised_text": "Delta."}],
                    }
                ),
            ),
            LLMResponse(
                provider="test",
                model="test",
                content=json.dumps(
                    {
                        "revisions": [{"paragraph_id": "p0001", "revised_text": "Too many words."}],
                    }
                ),
            ),
        ]
    )
    monkeypatch.setattr(config, "NARRATIVE_MAX_CHANGED_PARAGRAPHS", 1)
    monkeypatch.setattr(config, "NARRATIVE_MAX_WORD_DELTA_RATIO", 0.0)
    editor = NarrativeEditor(gateway)

    revised, applied = asyncio.run(editor.revise(draft, critique, {}, {}, None, "gpt-writing"))
    rejected, rejected_applied = asyncio.run(
        editor.revise(draft, critique, {}, {}, None, "gpt-writing")
    )

    assert applied is True
    assert revised == "Delta.\n\nBravo.\n\nCharlie."
    assert rejected == draft
    assert rejected_applied is False


def test_generation_pipeline_saves_raw_then_analyzes_targeted_revision(client, monkeypatch):
    import app.config as config
    from app.api.v1.story_generation_router import get_gateway
    from app.application.dto.story_dtos import LLMResponse

    raw_draft = (
        "Minh đặt bức thư lên bàn.\n\n"
        "Hắn nhận ra rằng mọi chuyện đã thay đổi.\n\n"
        "Ngoài cửa, tiếng chân dừng lại."
    )
    revised_paragraph = "Hắn gấp bức thư lại, chậm hơn thường ngày."
    analyzer_drafts = []
    revision_calls = 0
    writer_calls = 0

    async def generate(_model_alias, request, stream_handler=None, _tried=None):
        nonlocal revision_calls, writer_calls
        system = request.system_prompt.upper()
        if "PLANNER" in system:
            content = json.dumps(
                {
                    "chapter_goal": "Minh đọc bức thư",
                    "chapter_type": "revelation",
                    "target_word_count": 300,
                    "pov_character": "Minh",
                    "tone": "căng thẳng",
                    "required_scenes": [
                        {
                            "scene_id": "scene_1",
                            "objective": "Đọc thư",
                            "conflict": "Có người đang đến",
                            "participants": ["Minh"],
                            "location": "Thư phòng",
                            "mandatory_facts": [],
                            "state_before": [],
                            "state_after": [],
                            "forbidden_changes": [],
                        }
                    ],
                    "continuity_constraints": [],
                    "ending_hook": "Tiếng chân dừng ngoài cửa",
                },
                ensure_ascii=False,
            )
        elif "NARRATIVE_CRITIC" in system:
            content = json.dumps(
                {
                    "needs_revision": True,
                    "issues": [
                        {
                            "type": "authorial_conclusion",
                            "severity": "medium",
                            "paragraph_ids": ["p0002"],
                            "evidence": "Hắn nhận ra rằng...",
                            "reason": "Kết luận thay độc giả.",
                            "revision_instruction": "Giữ phản ứng, bỏ kết luận.",
                            "must_preserve": [],
                        }
                    ],
                },
                ensure_ascii=False,
            )
        elif "TARGETED_REVISER" in system:
            revision_calls += 1
            content = json.dumps(
                {
                    "revisions": [
                        {
                            "paragraph_id": "p0002",
                            "revised_text": revised_paragraph,
                        }
                    ],
                },
                ensure_ascii=False,
            )
        elif "STORY_ANALYZER" in system:
            analyzer_drafts.append(request.messages[0]["content"])
            content = json.dumps(
                {
                    "passed": True,
                    "score": 95,
                    "primary_issue_type": None,
                    "issues": [],
                }
            )
        else:
            writer_calls += 1
            content = raw_draft
        return LLMResponse(
            provider="test",
            model="test",
            content=content,
            finish_reason="stop",
        )

    gateway = MagicMock()
    gateway.get_embeddings = AsyncMock(return_value=[0.0])
    gateway.generate = AsyncMock(side_effect=generate)
    monkeypatch.setattr(config, "NARRATIVE_EDITING_ENABLED", True)
    app.dependency_overrides[get_gateway] = lambda: gateway
    story_id = uuid4()
    try:
        response = client.post(
            f"/api/v1/ai/stories/{story_id}/chapters/generate-sync",
            headers={
                "Idempotency-Key": str(uuid4()),
                "X-Tenant-Id": "tenant-phase-2",
                "X-User-Id": "user-phase-2",
            },
            json={
                "request": "Viết cảnh Minh đọc bức thư phản bội.",
                "model": "gpt-writing",
                "mode": "SYNC",
                "chapter": {"target_word_count": 300},
                "generation_config": {
                    "max_revision_attempts": 3,
                    "auto_analyze": True,
                },
            },
        )
    finally:
        app.dependency_overrides.pop(get_gateway, None)

    assert response.status_code == 200
    data = response.json()["data"]
    chapter_versions = sorted(
        (
            version
            for version in versions_db.values()
            if str(version["chapter_id"]) == data["chapter_id"]
        ),
        key=lambda version: version["version_number"],
    )
    assert [version["content"] for version in chapter_versions] == [
        raw_draft,
        raw_draft.replace("Hắn nhận ra rằng mọi chuyện đã thay đổi.", revised_paragraph),
    ]
    assert chapter_versions[0]["prompt_template_version"] == "chapter-writer-v2.0-raw"
    assert chapter_versions[1]["prompt_template_version"] == "chapter-writer-v2.0-revised"
    assert data["version_id"] == str(chapter_versions[1]["id"])
    assert writer_calls == 1
    assert revision_calls == 1
    assert revised_paragraph in analyzer_drafts[0]


def _run_decision_pipeline(monkeypatch, writer_contents, analyzer_side_effect, max_attempts):
    import app.application.orchestrators.story_generation_orchestrator as module
    import app.config as config
    from app.application.commands.story_commands import GenerateChapterCommand
    from app.application.dto.story_dtos import ChapterOptions, GenerationConfig, LLMResponse
    from app.application.orchestrators.story_generation_orchestrator import (
        StoryGenerationOrchestrator,
    )

    story_id = str(uuid4())
    job_id = str(uuid4())
    asyncio.run(
        mock_save_job(
            job_id,
            "tenant-decision",
            "user-decision",
            story_id,
            "GENERATE_CHAPTER",
            "QUEUED",
            "gpt-writing",
            str(uuid4()),
            {},
            max_attempts=max_attempts,
        )
    )
    command = GenerateChapterCommand(
        story_id=story_id,
        tenant_id="tenant-decision",
        user_id="user-decision",
        idempotency_key=str(uuid4()),
        request="Write a continuity-safe chapter.",
        model="gpt-writing",
        mode="SYNC",
        chapter=ChapterOptions(target_word_count=300),
        generation_config=GenerationConfig(
            max_revision_attempts=max_attempts,
            auto_analyze=True,
        ),
        constraints=[],
        metadata={"thread_id": "chat-source", "message_index": "2"},
    )
    plan = {
        "chapter_goal": "Continue the required event",
        "target_word_count": 300,
        "pov_character": "Minh",
        "required_scenes": [],
    }
    planner = MagicMock()
    planner.create_plan = AsyncMock(return_value=plan)
    planner.revise_plan = AsyncMock()
    retriever = MagicMock()
    retriever.gateway.get_embeddings = AsyncMock(return_value=[0.0])
    retriever.retrieve = AsyncMock(return_value={})
    retriever.retrieve_more = AsyncMock()
    prompt_builder = MagicMock()
    prompt_builder.build = AsyncMock(return_value=("WRITER", "Write"))
    gateway = MagicMock()
    gateway.generate = AsyncMock(
        side_effect=[
            LLMResponse(
                provider="test",
                model="test",
                content=item[0] if isinstance(item, tuple) else item,
                finish_reason=item[1] if isinstance(item, tuple) else "stop",
            )
            for item in writer_contents
        ]
    )
    analyzer = MagicMock()
    analyzer.analyze = AsyncMock(side_effect=analyzer_side_effect)
    narrative_editor = MagicMock()

    monkeypatch.setattr(config, "NARRATIVE_EDITING_ENABLED", False)
    monkeypatch.setattr(module, "publish_redis_stream", AsyncMock())
    orchestrator = StoryGenerationOrchestrator(
        planner,
        retriever,
        prompt_builder,
        gateway,
        analyzer,
        narrative_editor,
    )
    result = asyncio.run(orchestrator.execute(command, job_id))
    chapter_versions = sorted(
        (
            version
            for version in versions_db.values()
            if str(version["chapter_id"]) == result.get("chapter_id")
        ),
        key=lambda version: version["version_number"],
    )
    return result, chapter_versions, gateway, planner, retriever


def test_warning_is_ready_and_does_not_retry_writer_or_planner(monkeypatch):
    from app.application.dto.story_dtos import AnalysisResult, Issue

    warning = AnalysisResult(
        passed=False,
        score=25,
        issues=[
            Issue(
                type="DIRECT_CONTINUITY_CONTRADICTION",
                severity="MEDIUM",
                description="Possible, but unconfirmed, mismatch.",
            )
        ],
    )
    result, chapter_versions, gateway, planner, retriever = _run_decision_pipeline(
        monkeypatch,
        ["Usable raw draft."],
        [warning],
        max_attempts=3,
    )

    assert result["status"] == "READY_FOR_REVIEW"
    assert result["analysis"]["warnings"]
    assert result["analysis"]["blocking_issues"] == []
    assert gateway.generate.await_count == 1
    planner.revise_plan.assert_not_awaited()
    retriever.retrieve_more.assert_not_awaited()
    assert len(chapter_versions) == 1
    assert chapter_versions[0]["content"] == "Usable raw draft."
    assert chapter_versions[0]["generation_metadata"]["source"] == {
        "thread_id": "chat-source",
        "message_index": "2",
    }


def test_analyzer_exception_keeps_already_saved_raw_draft(monkeypatch):
    async def fail_after_raw_was_saved(*_args, **_kwargs):
        assert any(
            version["content"] == "Raw survives analyzer failure."
            for version in versions_db.values()
        )
        raise RuntimeError("validator unavailable")

    result, chapter_versions, gateway, planner, retriever = _run_decision_pipeline(
        monkeypatch,
        ["Raw survives analyzer failure."],
        fail_after_raw_was_saved,
        max_attempts=2,
    )

    assert result["status"] == "READY_FOR_REVIEW"
    assert result["analysis"]["passed"] is False
    assert result["analysis"]["primary_issue_type"] == "ANALYZER_UNAVAILABLE"
    assert result["analysis"]["needs_manual_review"] is True
    assert result["analysis"]["warnings"][0]["type"] == "ANALYZER_UNAVAILABLE"
    assert gateway.generate.await_count == 1
    planner.revise_plan.assert_not_awaited()
    retriever.retrieve_more.assert_not_awaited()
    assert [version["content"] for version in chapter_versions] == [
        "Raw survives analyzer failure."
    ]


def test_truncated_writer_auto_continues_and_saves_assembled_draft(monkeypatch):
    from app.application.dto.story_dtos import AnalysisResult

    accepted = AnalysisResult(passed=True, score=80, issues=[])
    first_part = " ".join(f"đầu{i}" for i in range(100))
    continuation = " ".join(f"kết{i}" for i in range(180)) + "."

    result, chapter_versions, gateway, planner, retriever = _run_decision_pipeline(
        monkeypatch,
        [(first_part, None), (continuation, None)],
        [accepted],
        max_attempts=0,
    )

    assembled = f"{first_part}\n\n{continuation}"
    assert result["status"] == "READY_FOR_REVIEW"
    assert result["content"] == assembled
    assert gateway.generate.await_count == 2
    assert [version["content"] for version in chapter_versions] == [
        first_part,
        assembled,
    ]
    assert chapter_versions[-1]["generation_metadata"]["continuation_rounds"] == 1
    assert chapter_versions[-1]["generation_metadata"]["continuation_incomplete"] is False
    planner.revise_plan.assert_not_awaited()
    retriever.retrieve_more.assert_not_awaited()


def test_only_allowlisted_high_issue_retries_full_writer(monkeypatch):
    from app.application.dto.story_dtos import AnalysisResult, Issue

    blocking = AnalysisResult(
        passed=True,
        score=95,
        issues=[
            Issue(
                type="MANDATORY_EVENT_LOSS",
                severity="HIGH",
                description="The required confrontation is absent.",
            )
        ],
    )
    accepted = AnalysisResult(passed=True, score=70, issues=[])
    result, chapter_versions, gateway, planner, retriever = _run_decision_pipeline(
        monkeypatch,
        ["First usable draft.", "Second usable draft."],
        [blocking, accepted],
        max_attempts=1,
    )

    assert result["status"] == "READY_FOR_REVIEW"
    assert result["content"] == "Second usable draft."
    assert gateway.generate.await_count == 2
    planner.revise_plan.assert_not_awaited()
    retriever.retrieve_more.assert_not_awaited()
    assert [version["status"] for version in chapter_versions] == [
        "DRAFT",
        "READY_FOR_REVIEW",
    ]


def test_job_fails_only_when_all_writer_attempts_are_empty(monkeypatch):
    result, chapter_versions, gateway, planner, retriever = _run_decision_pipeline(
        monkeypatch,
        [" ", ""],
        [],
        max_attempts=1,
    )

    assert result["status"] == "FAILED"
    assert gateway.generate.await_count == 2
    assert chapter_versions == []
    planner.revise_plan.assert_not_awaited()
    retriever.retrieve_more.assert_not_awaited()
