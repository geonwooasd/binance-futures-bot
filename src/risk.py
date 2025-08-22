import json, os, math, datetime, pytz
from .indicators import atr

def load_state(state_file: str):
    if not os.path.exists(state_file):
        return {"baseline_equity": None, "last_reset_date": None}
    with open(state_file, "r") as f:
        return json.load(f)

def save_state(state_file: str, data: dict):
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(data, f)

def ensure_daily_baseline(state, state_file, equity_now: float, kst_tz="Asia/Seoul"):
    kst = pytz.timezone(kst_tz)
    today = datetime.datetime.now(tz=kst).strftime("%Y-%m-%d")
    if state.get("last_reset_date") != today or state.get("baseline_equity") is None:
        state["baseline_equity"] = equity_now
        state["last_reset_date"] = today
        save_state(state_file, state)
    return state

def daily_dd_ok(state, equity_now: float, max_dd: float):
    base = state.get("baseline_equity")
    if not base or base <= 0:
        return True, 0.0
    dd = (equity_now - base) / base
    return dd >= max_dd, dd  # True면 거래 가능

def calc_qty_by_risk(df15, cfg, entry_price: float, side: str, equity: float):
    mode = cfg["strategy"].get("stop_tp_mode", "atr")
    if mode == "percent":
        sp = float(cfg["strategy"]["stop_percent"])
        if sp <= 0:
            return 0.0, entry_price
        if side == "LONG":
            stop = entry_price * (1 - sp)
            stop_dist = entry_price - stop
        else:
            stop = entry_price * (1 + sp)
            stop_dist = stop - entry_price
        risk_per_trade = cfg["risk"]["risk_per_trade"]
        qty = (equity * risk_per_trade) / max(stop_dist, 1e-8)
        return max(qty, 0.0), stop

    # ATR 기반(보존)
    n = cfg["strategy"]["atr_period"]
    m = cfg["strategy"]["atr_mult"]
    _atr = atr(df15, n).iloc[-1]
    if _atr is None or not (_atr == _atr) or _atr <= 0:
        return 0.0, entry_price
    if side == "LONG":
        stop = entry_price - m * _atr
        stop_dist = m * _atr
    else:
        stop = entry_price + m * _atr
        stop_dist = m * _atr
    risk_per_trade = cfg["risk"]["risk_per_trade"]
    qty = (equity * risk_per_trade) / max(stop_dist, 1e-8)
    return max(qty, 0.0), stop
