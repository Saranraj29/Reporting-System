from datetime import date, timedelta

from .base import ReportContext, ReportDef, register, week_start
from .common import summary_figures


def query(rc: ReportContext) -> dict:
    return summary_figures(rc)


def default_period(today: date) -> tuple[date, date]:
    start = week_start(today)
    return start, min(start + timedelta(days=6), today)


REPORT = register(ReportDef(
    key="weekly", title="Weekly report", required_permission="report.weekly.view",
    query=query, template="weekly.html", default_period=default_period,
))
