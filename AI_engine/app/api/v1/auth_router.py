import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.api.v1.responses import api_response
from app.infrastructure.auth.auth_service import (
    GoogleOAuthService,
    generate_reset_token,
    generate_session_id,
    hash_password,
    hash_token,
    verify_password,
)
from app.infrastructure.db.postgres_client import (
    claim_legacy_stories_for_user,
    create_password_reset_token,
    create_session,
    create_user_with_identity,
    delete_session,
    get_identity_with_user,
    get_session_user,
    get_user_by_email,
    get_user_identities,
    get_valid_password_reset_token,
    link_identity_to_user,
    reset_user_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Authentication"])

SESSION_COOKIE_NAME = "story_session"
OAUTH_STATE_COOKIE_NAME = "google_oauth_state"

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


# ==============================================================================
# PYDANTIC DTO SCHEMAS
# ==============================================================================

class RegisterRequest(BaseModel):
    display_name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str
    terms_agreed: bool = True


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    remember_me: bool = True


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=5)


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str


# ==============================================================================
# COOKIE HELPERS
# ==============================================================================

def _is_production() -> bool:
    return os.getenv("ENVIRONMENT", "").lower() in ("prod", "production")


def set_session_cookie(response: Response, session_id: str, remember_me: bool = True) -> None:
    max_age = 14 * 86400 if remember_me else 86400  # 14 days or 24 hours
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=_is_production(),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
    )


# ==============================================================================
# FASTAPI DEPENDENCIES
# ==============================================================================

async def get_current_user(request: Request) -> dict[str, Any]:
    """Retrieve the authenticated user from the session cookie.
    Raises HTTP 401 if unauthenticated or session expired.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "UNAUTHENTICATED",
                "message": "Vui lòng đăng nhập để tiếp tục.",
            },
        )

    user = await get_session_user(session_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "SESSION_EXPIRED",
                "message": "Phiên làm việc đã hết hạn. Vui lòng đăng nhập lại.",
            },
        )

    return user


async def get_optional_user(request: Request) -> dict[str, Any] | None:
    """Retrieve user if session cookie is valid; return None otherwise."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None
    try:
        return await get_session_user(session_id)
    except Exception:
        return None


def _validate_email(email: str) -> None:
    """Ensure email matches basic valid email format."""
    if not email or not EMAIL_REGEX.match(email.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "INVALID_EMAIL_FORMAT",
                "message": "Địa chỉ email không đúng định dạng.",
            },
        )


def _validate_password_strength(password: str) -> None:
    """Ensure password has at least 8 characters, an uppercase letter, and a number."""
    if len(password) < 8 or not re.search(r"[A-Z]", password) or not re.search(r"[0-9]", password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "PASSWORD_REQUIREMENTS_NOT_MET",
                "message": "Mật khẩu cần tối thiểu 8 ký tự, gồm ít nhất 1 chữ in hoa và 1 chữ số.",
            },
        )


def _user_payload(user: dict[str, Any], providers: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": str(user["id"]),
        "display_name": user["display_name"],
        "email": user["email"],
        "avatar_url": user.get("avatar_url"),
        "tier": user.get("tier", "author"),
        "linked_providers": providers or ["password"],
    }


# ==============================================================================
# AUTH API ENDPOINTS
# ==============================================================================

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, response: Response):
    """Register a new author account with email and password."""
    # 1. Validation
    _validate_email(req.email)
    if not req.terms_agreed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "TERMS_NOT_ACCEPTED",
                "message": "Bạn cần đồng ý với Điều khoản sử dụng và Chính sách bảo mật.",
            },
        )

    if req.password != req.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "PASSWORDS_DO_NOT_MATCH",
                "message": "Mật khẩu xác nhận không khớp với mật khẩu đã nhập.",
            },
        )

    _validate_password_strength(req.password)

    # 2. Check if email already registered
    existing_user = await get_user_by_email(req.email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "EMAIL_ALREADY_EXISTS",
                "message": "Địa chỉ email này đã được đăng ký. Bạn có muốn đăng nhập không?",
            },
        )

    # 3. Create user and password identity
    pw_hash = hash_password(req.password)
    user = await create_user_with_identity(
        email=req.email,
        display_name=req.display_name,
        provider="password",
        provider_user_id=req.email.strip().lower(),
        password_hash=pw_hash,
    )

    # 4. Automatically claim legacy stories for the first real author
    claimed_count = await claim_legacy_stories_for_user(user["id"])
    if claimed_count > 0:
        logger.info(f"Assigned {claimed_count} legacy stories to new user {user['id']}.")

    # 5. Create session
    session_id = generate_session_id()
    expires_at = datetime.now(UTC) + timedelta(days=14)
    await create_session(session_id, user["id"], expires_at)
    set_session_cookie(response, session_id, remember_me=True)

    return api_response(
        201,
        "Đăng ký tài khoản thành công",
        data={"user": _user_payload(user, ["password"])},
    )


@router.post("/login", status_code=status.HTTP_200_OK)
async def login(req: LoginRequest, response: Response):
    """Authenticate with email and password, establishing a server-side session."""
    normalized_email = req.email.strip().lower()
    identity = await get_identity_with_user("password", normalized_email)

    if not identity or not identity.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "INVALID_CREDENTIALS",
                "message": "Email hoặc mật khẩu chưa chính xác. Vui lòng kiểm tra lại.",
            },
        )

    if not verify_password(req.password, identity["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error_code": "INVALID_CREDENTIALS",
                "message": "Email hoặc mật khẩu chưa chính xác. Vui lòng kiểm tra lại.",
            },
        )

    if not identity.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error_code": "ACCOUNT_LOCKED",
                "message": "Tài khoản của bạn tạm thời bị khóa. Vui lòng liên hệ hỗ trợ.",
            },
        )

    user_id = identity["user_id"]
    user = {
        "id": user_id,
        "email": identity["email"],
        "display_name": identity["display_name"],
        "avatar_url": identity.get("avatar_url"),
        "tier": identity.get("tier", "author"),
    }

    # Create session
    session_id = generate_session_id()
    days = 14 if req.remember_me else 1
    expires_at = datetime.now(UTC) + timedelta(days=days)
    await create_session(session_id, user_id, expires_at)
    set_session_cookie(response, session_id, remember_me=req.remember_me)

    providers = await get_user_identities(user_id)
    return api_response(
        200,
        "Đăng nhập thành công",
        data={"user": _user_payload(user, providers)},
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(request: Request, response: Response):
    """Revoke session on server and clear session cookie on browser."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        try:
            await delete_session(session_id)
        except Exception as e:
            logger.warning(f"Error revoking session on logout: {e}")

    clear_session_cookie(response)
    return api_response(200, "Đăng xuất thành công", data=None)


@router.get("/me", status_code=status.HTTP_200_OK)
async def get_current_user_profile(current_user: dict[str, Any] = Depends(get_current_user)):
    """Fetch current authenticated user profile."""
    providers = await get_user_identities(current_user["id"])
    return api_response(
        200,
        "Phiên xác thực hợp lệ",
        data={"user": _user_payload(current_user, providers)},
    )


# ==============================================================================
# GOOGLE OAUTH 2.0 ENDPOINTS
# ==============================================================================

@router.get("/google/start")
async def google_auth_start():
    """Initiate Google OAuth 2.0 Authorization Code flow."""
    google_service = GoogleOAuthService()
    if not google_service.is_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "GOOGLE_AUTH_NOT_CONFIGURED",
                "message": "Google OAuth chưa được cấu hình Client ID và Secret trong file .env.",
            },
        )

    state = generate_session_id()
    auth_url = google_service.get_authorization_url(state)
    redirect_response = RedirectResponse(url=auth_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    # Store state cookie for anti-CSRF check directly on the RedirectResponse
    redirect_response.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state,
        max_age=600,  # 10 minutes
        httponly=True,
        samesite="lax",
        secure=_is_production(),
        path="/",
    )

    return redirect_response


@router.get("/google/callback")
async def google_auth_callback(
    request: Request,
    response: Response,
    code: str = Query(None),
    state: str = Query(None),
    error: str = Query(None),
):
    """Handle redirect callback from Google OAuth server."""
    if error or not code:
        logger.warning(f"Google OAuth denied or returned error: {error}")
        return RedirectResponse(url="/?auth_error=google_denied", status_code=status.HTTP_303_SEE_OTHER)

    # 1. Anti-CSRF state check
    expected_state = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    if not expected_state or expected_state != state:
        logger.error(f"Google OAuth CSRF mismatch: expected {expected_state}, got {state}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "OAUTH_CSRF_MISMATCH",
                "message": "Yêu cầu xác thực Google không hợp lệ hoặc đã hết hạn.",
            },
        )

    # 2. Exchange code with Google
    google_service = GoogleOAuthService()
    try:
        userinfo = await google_service.exchange_code_for_user_info(code)
    except Exception as e:
        logger.error(f"Failed to exchange Google OAuth code: {e}")
        return RedirectResponse(url="/?auth_error=google_failed", status_code=status.HTTP_303_SEE_OTHER)

    google_sub = userinfo["sub"]
    google_email = userinfo["email"]
    google_name = userinfo["name"]
    google_avatar = userinfo.get("picture")

    # 3. Check if Google identity exists
    identity = await get_identity_with_user("google", google_sub)
    if identity:
        user_id = identity["user_id"]
    else:
        # Check if a user with this email already exists (Account Linking)
        existing_user = await get_user_by_email(google_email)
        if existing_user:
            user_id = existing_user["id"]
            await link_identity_to_user(user_id, "google", google_sub)
            logger.info(f"Linked Google account ({google_sub}) to existing user ({google_email}).")
        else:
            # Create new user
            new_user = await create_user_with_identity(
                email=google_email,
                display_name=google_name,
                provider="google",
                provider_user_id=google_sub,
                password_hash=None,
                avatar_url=google_avatar,
            )
            user_id = new_user["id"]
            await claim_legacy_stories_for_user(user_id)
            logger.info(f"Created new user via Google OAuth: {google_email} ({user_id}).")

    # 4. Create session
    session_id = generate_session_id()
    expires_at = datetime.now(UTC) + timedelta(days=14)
    await create_session(session_id, user_id, expires_at)

    # Redirect home with session cookie
    redirect_response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(redirect_response, session_id, remember_me=True)
    redirect_response.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, path="/")
    return redirect_response


# ==============================================================================
# PASSWORD RESET ENDPOINTS
# ==============================================================================

@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(req: ForgotPasswordRequest):
    """Initiate password reset. Always returns 200 to prevent account enumeration."""
    user = await get_user_by_email(req.email)
    if user:
        plain_token, token_hash = generate_reset_token()
        expires_at = datetime.now(UTC) + timedelta(minutes=15)
        await create_password_reset_token(user["id"], token_hash, expires_at)
        logger.info(
            f"\n[AUTH NOTICE] Password reset requested for {user['email']}.\n"
            f"Reset Token: {plain_token}\n"
            f"Reset Link: http://localhost:8000/?reset_token={plain_token}\n"
        )

    return api_response(
        200,
        "Nếu email tồn tại trong hệ thống, hướng dẫn khôi phục đã được gửi.",
        data=None,
    )


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(req: ResetPasswordRequest):
    """Set a new password using a valid reset token."""
    if req.new_password != req.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error_code": "PASSWORDS_DO_NOT_MATCH",
                "message": "Mật khẩu xác nhận không khớp.",
            },
        )

    _validate_password_strength(req.new_password)

    token_hash = hash_token(req.token)
    token_record = await get_valid_password_reset_token(token_hash)
    if not token_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INVALID_OR_EXPIRED_RESET_TOKEN",
                "message": "Liên kết khôi phục mật khẩu không hợp lệ hoặc đã hết hạn.",
            },
        )

    new_hash = hash_password(req.new_password)
    await reset_user_password(token_record["id"], token_record["user_id"], new_hash)

    return api_response(200, "Đặt lại mật khẩu thành công. Vui lòng đăng nhập lại.", data=None)
