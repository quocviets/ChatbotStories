import hashlib
import hmac
import logging
import os
import secrets
import urllib.parse
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash a password securely using Python 3.11+ hashlib.scrypt with a random salt.

    Format: scrypt$n$r$p$salt_hex$hash_hex
    """
    n = 16384
    r = 8
    p = 1
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=32 * 1024 * 1024,
    )
    return f"scrypt${n}${r}${p}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plain password against a stored scrypt hash with timing-attack mitigation."""
    if not stored_hash or not password:
        return False
    try:
        parts = stored_hash.split("$")
        if len(parts) != 6 or parts[0] != "scrypt":
            return False
        _, n_str, r_str, p_str, salt_hex, hash_hex = parts
        n = int(n_str)
        r = int(r_str)
        p = int(p_str)
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)

        computed_hash = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            maxmem=32 * 1024 * 1024,
        )
        return hmac.compare_digest(computed_hash, expected_hash)
    except Exception as e:
        logger.warning(f"Password verification failed due to format error: {e}")
        return False


def generate_session_id() -> str:
    """Generate a secure, cryptographically random 256-bit session token."""
    return secrets.token_urlsafe(32)


def generate_reset_token() -> tuple[str, str]:
    """Generate a random plain token to send to the user and its SHA-256 hash to store."""
    plain_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(plain_token.encode("utf-8")).hexdigest()
    return plain_token, token_hash


def hash_token(plain_token: str) -> str:
    """Hash a token with SHA-256 for database lookup."""
    return hashlib.sha256(plain_token.encode("utf-8")).hexdigest()


class GoogleOAuthService:
    """Handles Google OAuth 2.0 Authorization Code exchange with Google's servers."""

    def __init__(self):
        self.client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        self.redirect_uri = os.getenv(
            "GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/api/v1/auth/google/callback"
        ).strip()
        self.auth_uri = "https://accounts.google.com/o/oauth2/v2/auth"
        self.token_uri = "https://oauth2.googleapis.com/token"
        self.userinfo_uri = "https://www.googleapis.com/oauth2/v3/userinfo"

    def is_configured(self) -> bool:
        """Return True if Google OAuth client ID and Secret are configured."""
        return bool(self.client_id and self.client_secret)

    def get_authorization_url(self, state: str) -> str:
        """Construct Google OAuth 2.0 consent screen redirect URL."""
        if not self.is_configured():
            raise ValueError(
                "Google OAuth chưa được cấu hình (thiếu GOOGLE_CLIENT_ID hoặc GOOGLE_CLIENT_SECRET)."
            )

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
        return f"{self.auth_uri}?{urllib.parse.urlencode(params)}"

    async def exchange_code_for_user_info(self, code: str) -> dict[str, Any]:
        """Exchange authorization code with Google token endpoint and retrieve user profile."""
        if not self.is_configured():
            raise ValueError("Google OAuth chưa được cấu hình.")

        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Exchange code for access token
            token_response = await client.post(
                self.token_uri,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )

            if token_response.status_code != 200:
                logger.error(
                    f"Google Token Exchange Error [{token_response.status_code}]: {token_response.text}"
                )
                raise ValueError("Không thể đổi mã xác thực với máy chủ Google.")

            token_data = token_response.json()
            access_token = token_data.get("access_token")
            if not access_token:
                raise ValueError("Máy chủ Google không trả về access_token.")

            # 2. Fetch userinfo
            userinfo_response = await client.get(
                self.userinfo_uri,
                headers={"Authorization": f"Bearer {access_token}"},
            )

            if userinfo_response.status_code != 200:
                logger.error(
                    f"Google Userinfo Error [{userinfo_response.status_code}]: {userinfo_response.text}"
                )
                raise ValueError("Không thể tải thông tin tài khoản từ Google.")

            userinfo = userinfo_response.json()
            email = userinfo.get("email")
            sub = userinfo.get("sub")

            if not email or not sub:
                raise ValueError("Dữ liệu tài khoản Google thiếu email hoặc Google ID.")

            return {
                "sub": str(sub),
                "email": str(email).lower().strip(),
                "name": userinfo.get("name") or email.split("@")[0],
                "picture": userinfo.get("picture"),
                "email_verified": bool(userinfo.get("email_verified", False)),
            }
