"""Database access. Every tenant session carries the company id and sets it on each transaction
(`SET LOCAL app.company_id`) so PostgreSQL row-level security applies even if a query forgets
its own filter."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
        _factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _factory = None


@event.listens_for(Session, "after_begin")
def _set_tenant(session: Session, transaction, connection) -> None:  # noqa: ARG001
    cid = session.info.get("company_id")
    if cid:
        connection.execute(text("SELECT set_config('app.company_id', :c, true)"), {"c": str(cid)})


def new_session(company_id=None) -> Session:
    get_engine()
    assert _factory is not None
    s = _factory()
    if company_id:
        s.info["company_id"] = str(company_id)
    return s


@contextmanager
def session_scope(company_id=None) -> Iterator[Session]:
    s = new_session(company_id)
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def anon_db() -> Iterator[Session]:
    """Session without a tenant: can only call the SECURITY DEFINER lookup functions."""
    s = new_session()
    try:
        yield s
    finally:
        s.close()
