import os
import pytest
from fastapi.testclient import TestClient
from uuid import uuid4

# Set up test configuration or remove existing SQLite file
sqlite_db_path = "ai_story_db.sqlite"
if os.path.exists(sqlite_db_path):
    try:
        os.remove(sqlite_db_path)
    except Exception:
        pass

from app.main import app

@pytest.fixture(scope="module", autouse=True)
def setup_database():
    yield
    # Cleanup after tests
    if os.path.exists(sqlite_db_path):
        try:
            os.remove(sqlite_db_path)
        except Exception:
            pass


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
