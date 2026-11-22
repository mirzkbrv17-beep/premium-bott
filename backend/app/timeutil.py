from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tashkent")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def tashkent_date(now: datetime | None = None) -> date:
    return (now or now_utc()).astimezone(TZ).date()


def tashkent_midnight_utc(d: date) -> datetime:
    return datetime.combine(d, time(0, 0), tzinfo=TZ).astimezone(timezone.utc)


def ceil_div(a: int, b: int) -> int:
    return -(-a // b)
