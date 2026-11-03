"""Report file storage. Local-disk backend; an S3 backend only has to implement put/get."""

import re
from pathlib import Path

from ..config import get_settings


def _root() -> Path:
    p = Path(get_settings().storage_dir).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe(key: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", key) or ".." in key:
        raise ValueError("invalid storage key")
    path = (_root() / key).resolve()
    if _root() not in path.parents:
        raise ValueError("invalid storage key")
    return path


def put(key: str, data: bytes) -> str:
    path = _safe(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return key


def get(key: str) -> bytes:
    return _safe(key).read_bytes()
