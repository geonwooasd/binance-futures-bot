from datetime import datetime, timedelta, timezone

def next_quarter_minute(now=None):
    now = now or datetime.now(timezone.utc)
    minute = ((now.minute // 15) + 1) * 15
    if minute >= 60:
        next_time = now.replace(minute=0, second=5, microsecond=0) + timedelta(hours=1)
    else:
        next_time = now.replace(minute=minute, second=5, microsecond=0)
    return next_time
