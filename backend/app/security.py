import base64
import hashlib
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

ALGO = "HS256"


# ----------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=get_settings().bcrypt_rounds)).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


# ----------------------------------------------------------------- tokens
def _encode(payload: dict[str, Any], ttl: timedelta) -> str:
    now = datetime.now(UTC)
    body = {**payload, "iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex}
    return jwt.encode(body, get_settings().jwt_secret, algorithm=ALGO)


def decode_token(token: str, purpose: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on any problem (bad signature, expired, wrong purpose)."""
    data = jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGO])
    if data.get("purpose") != purpose:
        raise jwt.InvalidTokenError("wrong token purpose")
    return data


def make_access_token(user_id, company_id) -> str:
    s = get_settings()
    return _encode(
        {"purpose": "access", "sub": str(user_id), "company_id": str(company_id)},
        timedelta(minutes=s.access_ttl_minutes),
    )


def make_refresh_token(user_id, company_id, version: int) -> str:
    s = get_settings()
    return _encode(
        {"purpose": "refresh", "sub": str(user_id), "company_id": str(company_id), "rv": version},
        timedelta(days=s.refresh_ttl_days),
    )


def make_email_token(purpose: str, hours: float, **claims: Any) -> str:
    return _encode({"purpose": purpose, **claims}, timedelta(hours=hours))


def password_fingerprint(password_hash: str | None) -> str:
    """Embedded in reset tokens so a token stops working once the password changes (single use)."""
    return hashlib.sha256((password_hash or "").encode()).hexdigest()[:16]


def new_share_token() -> str:
    return secrets.token_urlsafe(32)  # 32 random bytes


def make_file_token(key: str, ttl_seconds: int = 3600) -> str:
    return _encode({"purpose": "file", "key": key}, timedelta(seconds=ttl_seconds))


# ----------------------------------------------------------------- encryption at rest
def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().platform_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


# ----------------------------------------------------------------- tiny in-memory rate limiter
_hits: dict[str, list[float]] = {}


def rate_limited(key: str, limit: int, window: float = 60.0) -> bool:
    now = time.monotonic()
    bucket = [t for t in _hits.get(key, []) if now - t < window]
    if len(bucket) >= limit:
        _hits[key] = bucket
        return True
    bucket.append(now)
    _hits[key] = bucket
    return False


def reset_rate_limits() -> None:
    _hits.clear()
