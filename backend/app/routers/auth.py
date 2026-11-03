import logging
import uuid
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import anon_db, new_session
from ..errors import ApiError, bad_request, conflict
from ..models import Role, User, UserRole
from ..security import (
    decode_token,
    hash_password,
    make_access_token,
    make_email_token,
    make_refresh_token,
    password_fingerprint,
    rate_limited,
    verify_password,
)
from ..services import mail
from ..services.tenancy import provision_company

log = logging.getLogger("auth")

PUBLIC_DOMAINS = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "yahoo.com",
    "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "zoho.com", "mail.com",
}
COOKIE = "refresh_token"


def limit_auth(request: Request) -> None:
    s = get_settings()
    ip = request.client.host if request.client else "unknown"
    if s.auth_rate_limit_per_min and rate_limited(f"auth:{ip}", s.auth_rate_limit_per_min):
        raise ApiError(429, "rate_limited", "Too many attempts, try again in a minute")


router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(limit_auth)])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=120)
    company_name: str | None = Field(default=None, max_length=160)
    invite_token: str | None = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class GoogleIn(BaseModel):
    credential: str
    company_name: str | None = None


class TokenIn(BaseModel):
    token: str


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=128)


def _domain(email: str) -> str:
    return email.rsplit("@", 1)[1].lower()


def _company_by_domain(db: Session, domain: str):
    return db.execute(text("SELECT id, name FROM auth_company_by_domain(:d)"), {"d": domain}).first()


def _user_by_email(db: Session, email: str):
    return db.execute(text("SELECT * FROM auth_user_by_email(:e)"), {"e": email}).first()


def _set_refresh_cookie(resp: Response, user_id, company_id, version: int) -> None:
    s = get_settings()
    resp.set_cookie(
        COOKIE,
        make_refresh_token(user_id, company_id, version),
        max_age=s.refresh_ttl_days * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
    )


def _session_payload(user_id, company_id) -> dict:
    return {"access_token": make_access_token(user_id, company_id), "token_type": "bearer"}


def _send_verification(user: User) -> str:
    token = make_email_token("verify", 48, sub=str(user.id), company_id=str(user.company_id), email=user.email)
    link = f"{get_settings().public_web_url}/verify-email?token={token}"
    mail.send_email(user.email, "Verify your email", f"Hi {user.name},\n\nConfirm your email address:\n{link}\n")
    return token


def _create_user(
    email: str, name: str, password: str | None, google_id: str | None, company_name: str | None,
    invite_token: str | None, verified: bool,
) -> tuple[User, bool]:
    """Implements the join / create-company / invite rules. Returns (user, verified_already)."""
    domain = _domain(email)
    anon = new_session()
    try:
        if _user_by_email(anon, email):
            raise conflict("email_taken", "An account with this email already exists")
        company_id: uuid.UUID
        role_id: uuid.UUID | None = None
        new_company = False
        if invite_token:
            try:
                claims = decode_token(invite_token, "invite")
            except jwt.PyJWTError:
                raise bad_request("invalid_invite", "Invite link is invalid or expired") from None
            if claims["email"].lower() != email.lower():
                raise bad_request("invalid_invite", "Invite was issued for a different email address")
            company_id, role_id = uuid.UUID(claims["company_id"]), uuid.UUID(claims["role_id"])
            verified = True  # the invite was delivered to this address
        elif domain in PUBLIC_DOMAINS:
            raise bad_request("invite_required", "Personal email domains need an invite link from a company admin")
        else:
            found = _company_by_domain(anon, domain)
            if found:
                company_id = found.id
            else:
                if not company_name:
                    raise ApiError(409, "company_required", "No company uses this email domain yet; provide company_name")
                company_id, new_company = uuid.uuid4(), True
    finally:
        anon.close()

    db = new_session(company_id)
    try:
        if new_company:
            _, roles = provision_company(db, company_name or domain, domain)
            role_id = roles["Company Admin"].id
        elif role_id is None:
            role_id = db.execute(select(Role.id).where(Role.name == "Team Member")).scalar_one()
        user = User(
            company_id=company_id, email=email.lower(), name=name,
            password_hash=hash_password(password) if password else None, google_id=google_id,
            email_verified_at=datetime.now(UTC) if verified else None,
        )
        db.add(user)
        db.flush()
        db.add(UserRole(company_id=company_id, user_id=user.id, role_id=role_id))
        db.commit()
        return user, verified
    finally:
        db.close()


@router.get("/domain-check")
def domain_check(email: EmailStr, db: Session = Depends(anon_db)):
    domain = _domain(email)
    if domain in PUBLIC_DOMAINS:
        return {"status": "invite_required", "company_name": None}
    found = _company_by_domain(db, domain)
    if found:
        return {"status": "join", "company_name": found.name}
    return {"status": "create", "company_name": None}


@router.post("/register", status_code=201)
def register(body: RegisterIn):
    user, verified = _create_user(
        body.email, body.name, body.password, None, body.company_name, body.invite_token, verified=False
    )
    out: dict = {"message": "Account created", "verification_required": not verified}
    if not verified:
        token = _send_verification(user)
        if get_settings().app_env != "prod":
            out["dev_verification_token"] = token  # convenience while no real mail server is attached
    return out


@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(anon_db)):
    row = _user_by_email(db, body.email)
    if not row or not verify_password(body.password, row.password_hash) or not row.is_active:
        raise ApiError(401, "invalid_credentials", "Incorrect email or password")
    if row.email_verified_at is None:
        raise ApiError(403, "email_not_verified", "Verify your email address first")
    _set_refresh_cookie(response, row.id, row.company_id, row.refresh_version)
    return _session_payload(row.id, row.company_id)


def verify_google_credential(credential: str) -> dict:
    """Validates a Google Identity Services ID token. Replaced in tests."""
    client_id = get_settings().google_client_id
    if not client_id:
        raise ApiError(501, "google_not_configured", "Google sign-in is not configured")
    try:
        jwks = jwt.PyJWKClient("https://www.googleapis.com/oauth2/v3/certs")
        key = jwks.get_signing_key_from_jwt(credential)
        return jwt.decode(
            credential, key.key, algorithms=["RS256"], audience=client_id,
            issuer=["https://accounts.google.com", "accounts.google.com"],
        )
    except jwt.PyJWTError:
        raise ApiError(401, "invalid_google_token", "Google sign-in failed") from None


@router.post("/google")
def google(body: GoogleIn, response: Response):
    info = verify_google_credential(body.credential)
    email = (info.get("email") or "").lower()
    if not email or not info.get("email_verified"):
        raise ApiError(401, "invalid_google_token", "Google account email is not verified")
    anon = new_session()
    try:
        row = _user_by_email(anon, email)
    finally:
        anon.close()
    if row:
        if not row.is_active:
            raise ApiError(401, "invalid_credentials", "Account not available")
        db = new_session(row.company_id)
        try:
            user = db.get(User, row.id)
            user.google_id = user.google_id or info["sub"]
            user.email_verified_at = user.email_verified_at or datetime.now(UTC)
            db.commit()
        finally:
            db.close()
        uid, cid, version = row.id, row.company_id, row.refresh_version
    else:
        user, _ = _create_user(email, info.get("name") or email.split("@")[0], None, info["sub"],
                               body.company_name, None, verified=True)
        uid, cid, version = user.id, user.company_id, user.refresh_version
    _set_refresh_cookie(response, uid, cid, version)
    return _session_payload(uid, cid)


@router.post("/refresh")
def refresh(response: Response, refresh_token: str | None = Cookie(default=None)):
    if not refresh_token:
        raise ApiError(401, "unauthorized", "No refresh token")
    try:
        claims = decode_token(refresh_token, "refresh")
        uid, cid = uuid.UUID(claims["sub"]), uuid.UUID(claims["company_id"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise ApiError(401, "unauthorized", "Invalid refresh token") from None
    db = new_session(cid)
    try:
        user = db.get(User, uid)
        if not user or not user.is_active or user.email_verified_at is None or user.refresh_version != claims["rv"]:
            raise ApiError(401, "unauthorized", "Session expired")
        version = user.refresh_version
    finally:
        db.close()
    _set_refresh_cookie(response, uid, cid, version)  # rotated: a fresh token (new jti, new expiry) each time
    return _session_payload(uid, cid)


@router.post("/logout", status_code=204)
def logout(response: Response, refresh_token: str | None = Cookie(default=None)):
    if refresh_token:
        try:
            claims = decode_token(refresh_token, "refresh")
            db = new_session(claims["company_id"])
            try:
                user = db.get(User, uuid.UUID(claims["sub"]))
                if user:
                    user.refresh_version += 1  # revokes every outstanding refresh token for this user
                    db.commit()
            finally:
                db.close()
        except (jwt.PyJWTError, KeyError, ValueError):
            pass
    response.delete_cookie(COOKIE, path="/api/v1/auth")


@router.post("/verify-email")
def verify_email(body: TokenIn):
    try:
        claims = decode_token(body.token, "verify")
        uid, cid = uuid.UUID(claims["sub"]), uuid.UUID(claims["company_id"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise bad_request("invalid_token", "Verification link is invalid or expired") from None
    db = new_session(cid)
    try:
        user = db.get(User, uid)
        if not user or user.email.lower() != claims["email"].lower():
            raise bad_request("invalid_token", "Verification link is invalid or expired")
        if user.email_verified_at is None:
            user.email_verified_at = datetime.now(UTC)
            db.commit()
    finally:
        db.close()
    return {"message": "Email verified"}


@router.post("/forgot-password")
def forgot_password(body: ForgotIn, db: Session = Depends(anon_db)):
    row = _user_by_email(db, body.email)
    out: dict = {"message": "If the address is registered, a reset link has been sent"}
    if row and row.is_active:
        token = make_email_token(
            "reset", 1, sub=str(row.id), company_id=str(row.company_id), fp=password_fingerprint(row.password_hash)
        )
        link = f"{get_settings().public_web_url}/reset-password?token={token}"
        mail.send_email(row.email, "Reset your password", f"Use this link within one hour:\n{link}\n")
        if get_settings().app_env != "prod":
            out["dev_reset_token"] = token
    return out


@router.post("/reset-password")
def reset_password(body: ResetIn):
    try:
        claims = decode_token(body.token, "reset")
        uid, cid = uuid.UUID(claims["sub"]), uuid.UUID(claims["company_id"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise bad_request("invalid_token", "Reset link is invalid or expired") from None
    db = new_session(cid)
    try:
        user = db.get(User, uid)
        if not user or password_fingerprint(user.password_hash) != claims["fp"]:  # single use
            raise bad_request("invalid_token", "Reset link is invalid or already used")
        user.password_hash = hash_password(body.password)
        user.refresh_version += 1
        user.email_verified_at = user.email_verified_at or datetime.now(UTC)
        db.commit()
    finally:
        db.close()
    return {"message": "Password updated"}


