#!/usr/bin/env bash
set -e

REPO_NAME="binance-futures-bot-template"
echo "Creating repo: ${REPO_NAME}"
mkdir -p ${REPO_NAME}
cd ${REPO_NAME}

# 기본 디렉토리
mkdir -p config src data

# .gitignore
cat > .gitignore << 'EOF'
.venv/
__pycache__/
*.pyc
.env
data/*.sqlite
data/state.json
.DS_Store
EOF

# requirements
cat > requirements.txt << 'EOF'
ccxt==4.3.31
pandas==2.2.2
numpy==1.26.4
python-dotenv==1.0.1
requests==2.32.3
pytz==2024.1
PyYAML==6.0.2
loguru==0.7.2
apscheduler==3.10.4
EOF

# Dockerfile
cat > Dockerfile << 'EOF'
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY config ./config
COPY src ./src
COPY data ./data
ENV PYTHONPATH=/app/src
CMD ["python", "-m", "src.runner"]
EOF

# README
cat > README.md << 'EOF'
# Binance Futures Bot (Template)
- 15m 메인 + 1h 추세필터
- EMA20/50 돌파 + RSI 강도 + 금일 고/저 돌파
- 레버리지 5x, 일 손실 한도 -3%
- 기본은 페이퍼 모드(live=false), 실거래 전환 시 config/config.yaml 수정

## 빠른 시작
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example .env
PYTHONPATH=src python -m src.runner

## Docker
docker build -t trading-bot .
docker run -d --name bot --env-file .env trading-bot
EOF

# 예시 env
cat > config/.env.example << 'EOF'
BINANCE_KEY=your_key
BINANCE_SECRET=your_secret
DISCORD_WEBHOOK=https://discord.com/api/webhooks/...
EOF

# 설정
cat > config/config.yaml << 'EOF'
mode:
  live: false
  testnet: true
exchange:
  symbol: BTC/USDT
  leverage: 5
  margin_mode: ISOLATED
  fee_rate: 0.0004
strategy:
  base_tf: 15m
  htf: 1h
  rsi_long_range: [55, 70]
  rsi_short_range: [30, 45]
  ema_fast: 20
  ema_slow: 50
  atr_period: 14
  atr_mult: 1.8
risk:
  risk_per_trade: 0.01
  max_daily_dd: -0.03
  max_concurrent_positions: 2
notify:
  discord: true
runtime:
  kst_tz: Asia/Seoul
  align_to_candle: true
  run_on_minutes: [0, 15, 30, 45]
storage:
  state_file: data/state.json
EOF

# 소스코드
cat > src/__init__.py << 'EOF'
# package marker
EOF

cat > src/notifier.py << 'EOF'
import os, json, urllib.request
from dotenv import load_dotenv
load_dotenv()
WEBHOOK = os.getenv("DISCORD_WEBHOOK")

def notify(msg: str):
    print(msg)
    if not WEBHOOK:
        return
    try:
        data = json.dumps({"content": msg}).encode("utf-8")
        req = urllib.request.Request(WEBHOOK, data=data, headers={"Content-Type":"application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[notify error] {e}")
EOF

cat > src/indicators.py << 'EOF'
import numpy as np
import pandas as pd

def ema(s: pd.Series, n: int):
    return s.ewm(span=n, adjust=False).mean()

def rsi(close: pd.Series, n: int = 14):
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    rs = up / (down.replace(0, np.nan))
    return 100 - (100 / (1 + rs))

def atr(df: pd.DataFrame, n: int = 14):
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    a = (high - low).abs()
    b = (high - prev_close).abs()
    c = (low - prev_close).abs()
    tr = pd.concat([a, b, c], axis=1).max(axis=1)
    return tr.rolling(n).mean()
EOF

cat > src/broker.py << 'EOF'
import os
import ccxt
from dotenv import load_dotenv
from loguru import logger
load_dotenv()

def create_exchange(testnet: bool = True):
    ex = ccxt.binanceusdm({
        "apiKey": os.getenv("BINANCE_KEY"),
        "secret": os.getenv("BINANCE_SECRET"),
        "enableRateLimit": True,
        "options": {"defaultType": "future"}
    })
    try:
        ex.set_sandbox_mode(testnet)
    except Exception:
        pass
    try:
        ex.load_markets()
    except Exception as e:
        logger.warning(f"load_markets warn: {e}")
    return ex

def setup_leverage_and_mode(ex, symbol: str, leverage: int, margin_mode: str = "ISOLATED"):
    try:
        ex.set_margin_mode(margin_mode, symbol)
    except Exception as e:
        logger.warning(f"set_margin_mode warn: {e}")
    try:
        ex.set_leverage(leverage, symbol)
    except Exception as e:
        logger.warning(f"set_leverage warn: {e}")

def fetch_equity_usdt(ex):
    try:
        bal = ex.fetch_balance()
        usdt = bal.get("USDT", {})
        return usdt.get("total") or usdt.get("free") or 0.0
    except Exception as e:
        logger.warning(f"fetch_balance warn: {e}")
        return 0.0

def get_position_qty_side(ex, symbol: str):
    try:
        positions = ex.fetch_positions([symbol])
        for p in positions:
            qty = float(p.get("contracts") or 0.0)
            if qty > 0:
                return qty, "long"
            if qty < 0:
                return qty, "short"
            return 0.0, "flat"
    except Exception:
        pass
    try:
        pos = ex.fetch_position(symbol)
        qty = float(pos.get("contracts") or 0.0)
        if qty > 0:
            return qty, "long"
        if qty < 0:
            return qty, "short"
        return 0.0, "flat"
    except Exception:
        return 0.0, "flat"

def place_entry_market(ex, symbol: str, side: str, qty: float):
    assert side in ("buy", "sell")
    return ex.create_order(symbol=symbol, type="market", side=side, amount=qty)

def place_reduce_only_stop(ex, symbol: str, side: str, qty: float, stop_price: float):
    params = {"reduceOnly": True, "stopPrice": ex.price_to_precision(symbol, stop_price), "timeInForce": "GTC"}
    return ex.create_order(symbol, type="STOP_MARKET", side=side, amount=qty, params=params)

def close_position_market(ex, symbol: str, qty: float, current_side: str):
    side = "sell" if current_side == "long" else "buy"
    params = {"reduceOnly": True}
    return ex.create_order(symbol, type="market", side=side, amount=abs(qty), params=params)
EOF

cat > src/strategy.py << 'EOF'
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
EOF

cat > src/risk.py << 'EOF'
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
    return dd >= max_dd, dd

def calc_qty_by_risk(df15, cfg, entry_price: float, side: str, equity: float):
    n = cfg["strategy"]["atr_period"]
    m = cfg["strategy"]["atr_mult"]
    _atr = atr(df15, n).iloc[-1]
    if _atr is None or not (_atr == _atr) or _atr <= 0:  # NaN 체크
        return 0.0, entry_price
    if side == "LONG":
        stop = entry_price - m * _atr
        stop_dist = entry_price - stop
    else:
        stop = entry_price + m * _atr
        stop_dist = stop - entry_price
    risk_per_trade = cfg["risk"]["risk_per_trade"]
    qty = (equity * risk_per_trade) / max(stop_dist, 1e-8)
    return max(qty, 0.0), stop
EOF

cat > src/utils.py << 'EOF'
from datetime import datetime, timedelta, timezone

def next_quarter_minute(now=None):
    now = now or datetime.now(timezone.utc)
    minute = ((now.minute // 15) + 1) * 15
    if minute >= 60:
        next_time = now.replace(minute=0, second=5, microsecond=0) + timedelta(hours=1)
    else:
        next_time = now.replace(minute=minute, second=5, microsecond=0)
    return next_time
EOF

cat > src/runner.py << 'EOF'
import os, time, yaml
from datetime import datetime, timezone
from dotenv import load_dotenv
from .notifier import notify
from .broker import create_exchange, setup_leverage_and_mode, fetch_equity_usdt, get_position_qty_side, place_entry_market, place_reduce_only_stop
from .strategy import fetch_ohlcv, generate_signal
from .risk import load_state, ensure_daily_baseline, daily_dd_ok, calc_qty_by_risk
from .utils import next_quarter_minute

load_dotenv()

def main():
    with open("config/config.yaml", "r") as f:
        cfg = yaml.safe_load(f)
    ex = create_exchange(cfg["mode"]["testnet"])
    symbol = cfg["exchange"]["symbol"]
    setup_leverage_and_mode(ex, symbol, cfg["exchange"]["leverage"], cfg["exchange"]["margin_mode"])

    state_file = cfg["storage"]["state_file"]
    state = load_state(state_file)

    while True:
        now = datetime.now(timezone.utc)
        if cfg["runtime"]["align_to_candle"] and now.minute % 15 != 0:
            nxt = next_quarter_minute(now)
            time.sleep(max((nxt - now).total_seconds(), 1))
            continue

        try:
            df15 = fetch_ohlcv(ex, symbol, cfg["strategy"]["base_tf"], limit=600)
            df1h = fetch_ohlcv(ex, symbol, cfg["strategy"]["htf"], limit=600)
            price = float(df15["close"].iloc[-1])
        except Exception as e:
            notify(f"[ERR] OHLCV fetch 실패: {e}")
            time.sleep(5)
            continue

        equity_now = fetch_equity_usdt(ex) if cfg["mode"]["live"] else 10000.0
        state = ensure_daily_baseline(state, state_file, equity_now, cfg["runtime"]["kst_tz"])
        can_trade, dd = daily_dd_ok(state, equity_now, cfg["risk"]["max_daily_dd"])
        if not can_trade:
            notify(f"[가드] 일손실 한도 도달({dd:.2%}). 오늘 거래 중지.")
            time.sleep(60)
            continue

        try:
            signal = generate_signal(df15.copy(), df1h.copy(), cfg)
        except Exception as e:
            notify(f"[ERR] 신호 계산 실패: {e}")
            signal = None

        qty_open, pos_side = get_position_qty_side(ex, symbol)
        ts = now.astimezone().strftime("%Y-%m-%d %H:%M")

        if signal and pos_side == "flat":
            qty, stop = calc_qty_by_risk(df15, cfg, entry_price=price, side=signal, equity=equity_now)
            if qty <= 0:
                notify(f"[{ts}] 신호 {signal} 발생했지만 수량=0. 스킵.")
            else:
                if not cfg["mode"]["live"]:
                    notify(f"[페이퍼] {symbol} {signal} qty={qty:.4f} @ {price:.2f}, SL={stop:.2f}")
                else:
                    try:
                        side = "buy" if signal == "LONG" else "sell"
                        place_entry_market(ex, symbol, side, qty)
                        sl_side = "sell" if side == "buy" else "buy"
                        place_reduce_only_stop(ex, symbol, sl_side, qty, stop)
                        notify(f"[LIVE] {symbol} {signal} 진입 qty={qty:.4f} @~{price:.2f}, SL={stop:.2f}")
                    except Exception as e:
                        notify(f"[ERR] 진입 실패: {e}")
        else:
            notify(f"[{ts}] 신호:{signal or '없음'}, 보유:{pos_side}, 가격:{price:.2f}, DD:{dd:.2%}")

        nxt = next_quarter_minute()
        time.sleep(max((nxt - datetime.now(timezone.utc)).total_seconds(), 1))

if __name__ == "__main__":
    main()
EOF

echo "Done. Next steps:
1) cd ${REPO_NAME}
2) python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
3) cp config/.env.example .env  (키/웹훅 채우기)
4) PYTHONPATH=src python -m src.runner
"