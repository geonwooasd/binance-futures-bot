import os, time, yaml
from datetime import datetime, timezone
from dotenv import load_dotenv
from .notifier import notify
from .broker import (
    create_exchange,
    setup_leverage_and_mode,
    fetch_equity_usdt,
    get_position_qty_side,
    place_entry_market,
    place_reduce_only_stop,
)
from .strategy import fetch_ohlcv, generate_signal
from .risk import load_state, ensure_daily_baseline, daily_dd_ok, calc_qty_by_risk
from .utils import next_quarter_minute

load_dotenv()

def main():
    with open("config/config.yaml", "r") as f:
        cfg = yaml.safe_load(f)

    ex = create_exchange(cfg["mode"]["testnet"])
    symbol = cfg["exchange"]["symbol"]

    # live 모드에서만 레버리지/마진 설정(페이퍼일 땐 사설 API 호출 안 함)
    if cfg["mode"]["live"]:
        setup_leverage_and_mode(ex, symbol, cfg["exchange"]["leverage"], cfg["exchange"]["margin_mode"])

    state_file = cfg["storage"]["state_file"]
    state = load_state(state_file)

    while True:
        now = datetime.now(timezone.utc)
        if cfg["runtime"]["align_to_candle"] and now.minute % 15 != 0:
            nxt = next_quarter_minute(now)
            time.sleep(max((nxt - now).total_seconds(), 1))
            continue

        # 데이터 수집
        try:
            df15 = fetch_ohlcv(ex, symbol, cfg["strategy"]["base_tf"], limit=600)
            df1h = fetch_ohlcv(ex, symbol, cfg["strategy"]["htf"], limit=600)
            price = float(df15["close"].iloc[-1])
        except Exception as e:
            notify(f"[ERR] OHLCV fetch 실패: {e}")
            time.sleep(5)
            continue

        # 자본/데일리 가드
        equity_now = fetch_equity_usdt(ex) if cfg["mode"]["live"] else 10000.0
        state = ensure_daily_baseline(state, state_file, equity_now, cfg["runtime"]["kst_tz"])
        can_trade, dd = daily_dd_ok(state, equity_now, cfg["risk"]["max_daily_dd"])
        if not can_trade:
            notify(f"[가드] 일손실 한도 도달({dd:.2%}). 오늘 거래 중지.")
            time.sleep(60)
            continue

        # 신호 계산
        try:
            signal = generate_signal(df15.copy(), df1h.copy(), cfg)
        except Exception as e:
            notify(f"[ERR] 신호 계산 실패: {e}")
            signal = None

        # 포지션 조회(live일 때만), 페이퍼면 항상 flat
        if cfg["mode"]["live"]:
            qty_open, pos_side = get_position_qty_side(ex, symbol)
        else:
            qty_open, pos_side = 0.0, "flat"

        ts = now.astimezone().strftime("%Y-%m-%d %H:%M")

        if signal and pos_side == "flat":
            qty, stop = calc_qty_by_risk(df15, cfg, entry_price=price, side=signal, equity=equity_now)
            if qty <= 0:
                notify(f"[{ts}] 신호 {signal} 발생했지만 수량=0. 스킵.")
            else:
                if not cfg["mode"]["live"]:
                    notify(f"[페이퍼] {symbol} {signal} qty={qty:.6f} @ {price:.2f}, SL={stop:.2f}")
                else:
                    try:
                        side = "buy" if signal == "LONG" else "sell"
                        place_entry_market(ex, symbol, side, qty)
                        sl_side = "sell" if side == "buy" else "buy"
                        place_reduce_only_stop(ex, symbol, sl_side, qty, stop)
                        notify(f"[LIVE] {symbol} {signal} 진입 qty={qty:.6f} @~{price:.2f}, SL={stop:.2f}")
                    except Exception as e:
                        notify(f"[ERR] 진입 실패: {e}")
        else:
            notify(f"[{ts}] 신호:{signal or '없음'}, 보유:{pos_side}, 가격:{price:.2f}, DD:{dd:.2%}")

        nxt = next_quarter_minute()
        time.sleep(max((nxt - datetime.now(timezone.utc)).total_seconds(), 1))

if __name__ == "__main__":
    main()
