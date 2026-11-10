"""Time off: each person's own leave and the company holidays. Reminders are not sent on those days (see services/timeoff.py)."""

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from ..deps import Ctx, get_ctx, require
from ..errors import not_found
from ..models import TimeOff

router = APIRouter(tags=["time-off"])
MAX_DAYS = 366


class RangeIn(BaseModel):
    start_date: date
    end_date: date
    note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _check(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date")
        if self.end_date - self.start_date > timedelta(days=MAX_DAYS):
            raise ValueError(f"a period can be at most {MAX_DAYS} days")
        return self


def _out(t: TimeOff) -> dict:
    return {"id": str(t.id), "start_date": t.start_date.isoformat(), "end_date": t.end_date.isoformat(), "note": t.note}


def _add(ctx: Ctx, body: RangeIn, user_id: uuid.UUID | None) -> dict:
    row = TimeOff(company_id=ctx.company_id, user_id=user_id, start_date=body.start_date, end_date=body.end_date,
                  note=body.note.strip(), created_by=ctx.me.id)
    ctx.db.add(row)
    ctx.db.commit()
    return _out(row)


def _delete(ctx: Ctx, row_id: uuid.UUID, user_id: uuid.UUID | None, what: str) -> None:
    row = ctx.db.get(TimeOff, row_id)
    if row is None or row.user_id != user_id:  # leave ids never open a holiday and the other way round; RLS already hides other companies
        raise not_found(what)
    ctx.db.delete(row)
    ctx.db.commit()


# --------------------------------------------------------------------------- my leave
@router.get("/leave")
def my_leave(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(select(TimeOff).where(TimeOff.user_id == ctx.me.id).order_by(TimeOff.start_date.desc()).limit(200)).scalars()
    return {"items": [_out(t) for t in rows]}


@router.post("/leave", status_code=201)
def add_leave(body: RangeIn, ctx: Ctx = Depends(get_ctx)):
    return _add(ctx, body, ctx.me.id)


@router.delete("/leave/{leave_id}", status_code=204)
def delete_leave(leave_id: uuid.UUID, ctx: Ctx = Depends(get_ctx)):
    _delete(ctx, leave_id, ctx.me.id, "Leave")  # only your own leave


# --------------------------------------------------------------------------- company holidays
@router.get("/holidays")
def holidays(ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.execute(select(TimeOff).where(TimeOff.user_id.is_(None)).order_by(TimeOff.start_date.desc()).limit(200)).scalars()
    return {"items": [_out(t) for t in rows]}


@router.post("/holidays", status_code=201)
def add_holiday(body: RangeIn, ctx: Ctx = Depends(require("settings.manage"))):
    return _add(ctx, body, None)


@router.delete("/holidays/{holiday_id}", status_code=204)
def delete_holiday(holiday_id: uuid.UUID, ctx: Ctx = Depends(require("settings.manage"))):
    _delete(ctx, holiday_id, None, "Holiday")
