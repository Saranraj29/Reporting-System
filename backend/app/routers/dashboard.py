import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query

from ..deps import Ctx, require
from ..errors import bad_request
from ..services.dashboard import dashboard, default_range, effective_user_ids
from ..services.timeutil import company_today

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def get_dashboard(
    project: uuid.UUID | None = None, user: uuid.UUID | None = None,
    from_: date | None = Query(default=None, alias="from"), to: date | None = None,
    ctx: Ctx = Depends(require("dashboard.view")),
):
    today = company_today(ctx.company.timezone)
    d_from, d_to = default_range(today)
    start, end = from_ or d_from, to or today
    if end < start:
        raise bad_request("invalid_range", "'to' cannot be before 'from'")
    uids = effective_user_ids(ctx.visible("dashboard.view"), user)
    return dashboard(ctx.db, ctx.company_id, ctx.me.id, uids, project, start, end, today)
