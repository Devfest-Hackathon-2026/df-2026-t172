"""日本時間の時刻と、保存したデータの期限（TTL）。"""

from datetime import UTC, datetime, time, timedelta, timezone

JST = timezone(timedelta(hours=9), "JST")


def now_jst() -> datetime:
    """今の日本時間。"""
    return datetime.now(UTC).astimezone(JST)


def expires_at(created: datetime) -> datetime:
    """作った日の翌日0時（日本時間）。Firestore の TTL でこの時刻以降に消す。"""
    next_day = created.astimezone(JST).date() + timedelta(days=1)
    return datetime.combine(next_day, time(0, 0), tzinfo=JST)


def iso(moment: datetime) -> str:
    """ISO 8601 の文字列（秒まで、日本時間）。"""
    return moment.astimezone(JST).isoformat(timespec="seconds")
