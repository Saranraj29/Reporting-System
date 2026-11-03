from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def tzinfo(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def company_now(tz_name: str | None, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(tzinfo(tz_name))


def company_today(tz_name: str | None) -> date:
    return company_now(tz_name).date()


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False
