import pandas as pd
from .indicators import ema, rsi

def fetch_ohlcv(ex, symbol: str, tf: str, limit: int = 500) -> pd.DataFrame:
    raw = ex.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
    df = pd.DataFrame(raw, columns=["ts","open","high","low","close","volume"])
    df["time"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("time")[["open","high","low","close","volume"]]

def intraday_high_low(df15: pd.DataFrame, tz="Asia/Seoul"):
    kst = df15.tz_convert(tz)
    today_start = kst.index[-1].normalize()
    mask = kst.index >= today_start
    high_ = kst.loc[mask, "high"].max()
    low_ = kst.loc[mask, "low"].min()
    return float(high_), float(low_)

def generate_signal(df15: pd.DataFrame, df1h: pd.DataFrame, cfg) -> str | None:
    f, s = cfg["strategy"]["ema_fast"], cfg["strategy"]["ema_slow"]
    r_lo, r_hi = cfg["strategy"]["rsi_long_range"]
    s_lo, s_hi = cfg["strategy"]["rsi_short_range"]

    df15["ema_f"] = ema(df15["close"], f)
    df15["ema_s"] = ema(df15["close"], s)
    df15["rsi14"] = rsi(df15["close"], 14)

    df1h["ema50"] = ema(df1h["close"], 50)
    df15["ema50_1h"] = df1h["ema50"].reindex(df15.index).ffill()
    df15 = df15.dropna(subset=["ema_f","ema_s","rsi14","ema50_1h"])

    last, prev = df15.iloc[-1], df15.iloc[-2]
    cross_up = prev["ema_f"] <= prev["ema_s"] and last["ema_f"] > last["ema_s"]
    cross_dn = prev["ema_f"] >= prev["ema_s"] and last["ema_f"] < last["ema_s"]

    long_ok = (last["close"] > last["ema50_1h"]) and (r_lo <= last["rsi14"] <= r_hi)
    short_ok = (last["close"] < last["ema50_1h"]) and (s_lo <= last["rsi14"] <= s_hi)

    day_high, day_low = intraday_high_low(df15)
    long_break = last["close"] > day_high
    short_break = last["close"] < day_low

    if cross_up and long_ok and long_break:
        return "LONG"
    if cross_dn and short_ok and short_break:
        return "SHORT"
    return None
