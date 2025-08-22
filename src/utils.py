from datetime import datetime, timedelta, timezone
import pytz

def next_quarter_minute(now=None):
    now = now or datetime.now(timezone.utc)
    minute = ((now.minute // 15) + 1) * 15
    if minute >= 60:
        return now.replace(minute=0, second=5, microsecond=0) + timedelta(hours=1)
    return now.replace(minute=minute, second=5, microsecond=0)

def in_trade_window_kst(now_utc, start_end=("00:00","23:59"), kst_tz="Asia/Seoul"):
    kst = pytz.timezone(kst_tz)
    t = now_utc.astimezone(kst)
    s, e = start_end
    s_h, s_m = map(int, s.split(":"))
    e_h, e_m = map(int, e.split(":"))
    start = t.replace(hour=s_h, minute=s_m, second=0, microsecond=0)
    end   = t.replace(hour=e_h, minute=e_m, second=59, microsecond=0)
    return start <= t <= end

def near_funding_window(now_utc, minutes=5):
    anchors = [0, 8, 16]  # UTC 기준 펀딩 시각
    h = now_utc.hour
    m = now_utc.minute
    for ah in anchors:
        diff = abs(((ah - h) * 60) + (0 - m))
        if diff <= minutes:
            return True
    return False
