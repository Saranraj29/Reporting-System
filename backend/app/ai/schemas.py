"""What the model must return. One JSON schema per call (strict-mode compatible: every field present, nullable instead of optional,
no free-form maps) and one Pydantic model that validates the answer in code."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class SectionOut(BaseModel):
    title: str
    scope: Literal["overall", "per_project"] = "overall"
    kind: Literal["block", "text"] = "text"
    block: str | None = None
    brief: str | None = None
    style: str | None = None
    label: str | None = None


class OutlineOut(BaseModel):
    title: str = "Project Report"
    heading_level: Literal[1, 2] = 2
    notes: str = ""
    sections: list[SectionOut] = Field(min_length=1)


class TextItem(BaseModel):
    key: str
    text: str


class NarrativeOut(BaseModel):
    items: list[TextItem]


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_S, _SN = {"type": "string"}, {"type": ["string", "null"]}

OUTLINE_SCHEMA = _obj({
    "title": _S, "heading_level": {"type": "integer", "enum": [1, 2]}, "notes": _S,
    "sections": {"type": "array", "items": _obj({
        "title": _S, "scope": {"type": "string", "enum": ["overall", "per_project"]}, "kind": {"type": "string", "enum": ["block", "text"]},
        "block": _SN, "brief": _SN, "style": _SN, "label": _SN,
    })},
})
NARRATIVE_SCHEMA = _obj({"items": {"type": "array", "items": _obj({"key": _S, "text": _S})}})
