import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query

from ..deps import Ctx, require
from ..errors import bad_request
from ..services.access import owned_project_ids
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
    visible = ctx.visible("dashboard.view")
    owned = owned_project_ids(ctx.db, ctx.me.id)
    status_uids = effective_user_ids(visible, user)  # daily-status text is never widened by project ownership
    uids, owned_only = status_uids, False
    if owned and visible is not None and user is not None and user not in visible:
        uids, owned_only = [user], True  # someone outside my scope: only their work inside projects I own
    widen = bool(owned) and visible is not None and user is None
    return dashboard(ctx.db, ctx.company_id, ctx.me.id, uids, project, start, end, today, owned=owned,
                     owned_only=owned_only, widen=widen, status_uids=status_uids)
