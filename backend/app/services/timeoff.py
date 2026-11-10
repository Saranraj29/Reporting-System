"""Time off: company holidays and personal leave. Reminders are not sent on a holiday, nor to someone on leave."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import TimeOff


def is_company_holiday(db: Session, day: date) -> bool:
    row = db.execute(
        select(TimeOff.id).where(TimeOff.user_id.is_(None), TimeOff.start_date <= day, TimeOff.end_date >= day).limit(1)
    ).first()
    return row is not None


def users_on_leave(db: Session, day: date) -> set[uuid.UUID]:
    rows = db.execute(
        select(TimeOff.user_id).where(TimeOff.user_id.is_not(None), TimeOff.start_date <= day, TimeOff.end_date >= day)
    ).scalars()
    return set(rows)
