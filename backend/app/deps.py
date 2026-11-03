import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import new_session
from .errors import ApiError, forbidden
from .models import Company, User
from .perms import PERMISSIONS, best_scope
from .security import decode_token
from .services.access import load_permissions, visible_users

bearer = HTTPBearer(auto_error=False)


@dataclass
class Ctx:
    db: Session
    me: User
    company_id: uuid.UUID
    perms: frozenset[str]
    scope: str | None = None
    _company: Company | None = field(default=None, repr=False)

    @property
    def company(self) -> Company:
        if self._company is None:
            self._company = self.db.get(Company, self.company_id)
        return self._company

    def has(self, key: str) -> bool:
        return key in self.perms

    def scope_of(self, base: str) -> str | None:
        return best_scope(self.perms, base)

    def visible(self, base: str) -> set[uuid.UUID] | None:
        """User ids covered by my scope for `base` (None = everyone in the company)."""
        scope, ids = visible_users(self.db, self.me.id, self.perms, base)
        if scope is None:
            raise forbidden()
        return ids


def unauthorized(msg: str = "Authentication required") -> ApiError:
    return ApiError(401, "unauthorized", msg)


def get_ctx(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Iterator[Ctx]:
    if creds is None:
        raise unauthorized()
    try:
        claims = decode_token(creds.credentials, "access")
        user_id, company_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["company_id"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized("Invalid or expired token") from None
    db = new_session(company_id)  # the tenant comes from the signed JWT only
    try:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            raise unauthorized("Account not available")
        if user.email_verified_at is None:
            raise ApiError(403, "email_not_verified", "Verify your email address first")
        ctx = Ctx(db=db, me=user, company_id=company_id, perms=load_permissions(db, user_id))
        request.state.user_id, request.state.company_id = str(user_id), str(company_id)
        yield ctx
    finally:
        db.close()


def require(key: str) -> Callable[..., Ctx]:
    """Route guard. `key` is either an exact permission key (report.approve) or an area.action base
    (task.view) in which case the highest scope the user holds is placed on ctx.scope."""

    def dep(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        if key in PERMISSIONS:
            if key not in ctx.perms:
                raise forbidden()
        else:
            scope = best_scope(ctx.perms, key)
            if scope is None:
                raise forbidden()
            ctx.scope = scope
        return ctx

    return dep


def require_any(*keys: str) -> Callable[..., Ctx]:
    def dep(ctx: Ctx = Depends(get_ctx)) -> Ctx:
        if not any((k in ctx.perms) if k in PERMISSIONS else best_scope(ctx.perms, k) for k in keys):
            raise forbidden()
        return ctx

    return dep


@dataclass
class Page:
    page: int
    limit: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


def pagination(page: int = 1, limit: int = 50) -> Page:
    if page < 1 or limit < 1 or limit > 200:
        raise ApiError(422, "validation_error", "page must be >= 1 and limit between 1 and 200")
    return Page(page, limit)


def paged(db: Session, stmt, page: Page, serialize: Callable[[Any], Any]) -> dict:
    total = db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = db.execute(stmt.limit(page.limit).offset(page.offset)).scalars().all()
    return {"items": [serialize(r) for r in rows], "total": total, "page": page.page, "limit": page.limit}


def now_utc() -> datetime:
    return datetime.now(UTC)
