import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app.infrastructure.auth.auth_service import (
    GoogleOAuthService,
    generate_reset_token,
    generate_session_id,
    hash_password,
    hash_token,
    verify_password,
)
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


# ==============================================================================
# 1. UNIT TESTS: CRYPTO & HASHING (SCRYPT & HMAC)
# ==============================================================================

def test_hash_password_and_verify_success():
    password = "MySecurePassword123"
    hashed = hash_password(password)

    assert hashed.startswith("scrypt$16384$8$1$")
    assert verify_password(password, hashed) is True


def test_verify_password_failure():
    password = "CorrectPassword123"
    hashed = hash_password(password)

    assert verify_password("WrongPassword123", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(password, "") is False
    assert verify_password(password, "invalid$format") is False


def test_generate_session_id_entropy():
    s1 = generate_session_id()
    s2 = generate_session_id()
    assert len(s1) >= 32
    assert s1 != s2


def test_reset_token_generation_and_hash():
    plain, token_hash = generate_reset_token()
    assert len(plain) >= 32
    assert len(token_hash) == 64  # SHA-256 hex
    assert hash_token(plain) == token_hash


def test_google_oauth_service_unconfigured():
    with patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""}):
        service = GoogleOAuthService()
        assert service.is_configured() is False
        with pytest.raises(ValueError, match="chưa được cấu hình"):
            service.get_authorization_url("state123")


def test_google_oauth_service_configured():
    with patch.dict(
        "os.environ",
        {
            "GOOGLE_CLIENT_ID": "mock-client-id",
            "GOOGLE_CLIENT_SECRET": "mock-secret",
            "GOOGLE_REDIRECT_URI": "http://localhost:8000/callback",
        },
    ):
        service = GoogleOAuthService()
        assert service.is_configured() is True
        url = service.get_authorization_url("test-state-xyz")
        assert "accounts.google.com" in url
        assert "client_id=mock-client-id" in url
        assert "state=test-state-xyz" in url


def test_google_auth_start_sets_cookie_and_redirects():
    with patch.dict(
        "os.environ",
        {
            "GOOGLE_CLIENT_ID": "mock-client-id",
            "GOOGLE_CLIENT_SECRET": "mock-secret",
            "GOOGLE_REDIRECT_URI": "http://127.0.0.1:8000/api/v1/auth/google/callback",
        },
    ):
        fresh_client = TestClient(app, follow_redirects=False)
        res = fresh_client.get("/api/v1/auth/google/start")
        assert res.status_code == 307
        assert "google_oauth_state" in res.cookies
        state_cookie = res.cookies["google_oauth_state"]
        location = res.headers.get("location")
        assert f"state={state_cookie}" in location
        assert "accounts.google.com" in location


def test_google_auth_callback_csrf_mismatch():
    fresh_client = TestClient(app, follow_redirects=False)
    # Case 1: No cookie
    res = fresh_client.get("/api/v1/auth/google/callback?code=abc&state=xyz")
    assert res.status_code == 400
    assert res.json()["detail"]["error_code"] == "OAUTH_CSRF_MISMATCH"

    # Case 2: Cookie does not match state
    fresh_client.cookies.set("google_oauth_state", "different_state")
    res = fresh_client.get("/api/v1/auth/google/callback?code=abc&state=xyz")
    assert res.status_code == 400
    assert res.json()["detail"]["error_code"] == "OAUTH_CSRF_MISMATCH"


# ==============================================================================
# 2. INTEGRATION TESTS: FASTAPI AUTH ENDPOINTS
# ==============================================================================

def test_register_validation_password_mismatch():
    res = client.post(
        "/api/v1/auth/register",
        json={
            "display_name": "Nam Cao",
            "email": "namcao@example.com",
            "password": "Password123",
            "confirm_password": "DifferentPassword123",
            "terms_agreed": True,
        },
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "PASSWORDS_DO_NOT_MATCH"


def test_register_validation_weak_password():
    res = client.post(
        "/api/v1/auth/register",
        json={
            "display_name": "Nam Cao",
            "email": "namcao@example.com",
            "password": "password",
            "confirm_password": "password",
            "terms_agreed": True,
        },
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "PASSWORD_REQUIREMENTS_NOT_MET"


def test_register_validation_terms_not_agreed():
    res = client.post(
        "/api/v1/auth/register",
        json={
            "display_name": "Nam Cao",
            "email": "namcao@example.com",
            "password": "Password123",
            "confirm_password": "Password123",
            "terms_agreed": False,
        },
    )
    assert res.status_code == 422
    assert res.json()["detail"]["error_code"] == "TERMS_NOT_ACCEPTED"


def test_register_and_login_flow():
    mock_user_id = uuid4()
    mock_user = {
        "id": mock_user_id,
        "email": "tacgia.moi@example.com",
        "display_name": "Tác Giả Mới",
        "avatar_url": None,
        "tier": "author",
        "is_active": True,
    }

    with (
        patch("app.api.v1.auth_router.get_user_by_email", new_callable=AsyncMock) as mock_get_email,
        patch("app.api.v1.auth_router.create_user_with_identity", new_callable=AsyncMock) as mock_create,
        patch("app.api.v1.auth_router.claim_legacy_stories_for_user", new_callable=AsyncMock) as mock_claim,
        patch("app.api.v1.auth_router.create_session", new_callable=AsyncMock) as mock_create_session,
    ):
        mock_get_email.return_value = None
        mock_create.return_value = mock_user
        mock_claim.return_value = 1

        res = client.post(
            "/api/v1/auth/register",
            json={
                "display_name": "Tác Giả Mới",
                "email": "tacgia.moi@example.com",
                "password": "Password123",
                "confirm_password": "Password123",
                "terms_agreed": True,
            },
        )

        assert res.status_code == 201
        data = res.json()["data"]
        assert data["user"]["email"] == "tacgia.moi@example.com"
        assert "story_session" in res.cookies


def test_login_invalid_credentials():
    with patch("app.api.v1.auth_router.get_identity_with_user", new_callable=AsyncMock) as mock_get_id:
        mock_get_id.return_value = None

        res = client.post(
            "/api/v1/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "Password123",
            },
        )
        assert res.status_code == 401
        assert res.json()["detail"]["error_code"] == "INVALID_CREDENTIALS"


def test_get_me_unauthenticated():
    fresh_client = TestClient(app)
    res = fresh_client.get("/api/v1/auth/me")
    assert res.status_code == 401
    assert res.json()["detail"]["error_code"] == "UNAUTHENTICATED"


def test_get_me_authenticated():
    mock_user_id = uuid4()
    mock_user = {
        "id": mock_user_id,
        "email": "user@example.com",
        "display_name": "Tác Giả",
        "avatar_url": None,
        "tier": "author",
        "is_active": True,
    }
    with (
        patch("app.api.v1.auth_router.get_session_user", new_callable=AsyncMock) as mock_session_user,
        patch("app.api.v1.auth_router.get_user_identities", new_callable=AsyncMock) as mock_identities,
    ):
        mock_session_user.return_value = mock_user
        mock_identities.return_value = ["password"]

        fresh_client = TestClient(app, cookies={"story_session": "valid_session_token_123"})
        res = fresh_client.get("/api/v1/auth/me")
        assert res.status_code == 200
        assert res.json()["data"]["user"]["email"] == "user@example.com"


def test_logout():
    fresh_client = TestClient(app, cookies={"story_session": "token_to_clear"})
    with patch("app.api.v1.auth_router.delete_session", new_callable=AsyncMock):
        res = fresh_client.post("/api/v1/auth/logout")
        assert res.status_code == 200


def test_forgot_password_always_200():
    fresh_client = TestClient(app)
    with patch("app.api.v1.auth_router.get_user_by_email", new_callable=AsyncMock) as mock_get_email:
        mock_get_email.return_value = None

        res = fresh_client.post(
            "/api/v1/auth/forgot-password",
            json={"email": "anyone@example.com"},
        )
        assert res.status_code == 200
        assert "data" in res.json()
