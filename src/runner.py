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
from .strategy_loader import load_strategy
from .risk import load_state, save_state, ensure_daily_baseline, daily_dd_ok, calc_qty_by_risk
from .utils import next_quarter_minute, in_trade_window_kst, near_funding_window

load_dotenv()

def _compute_tp_by_percent(entry: float, side: str, p: float):
    if side == "LONG":
        return entry * (1 + p)
    else:
        return entry * (1 - p)

def _load_paper_pos(state: dict):
    return state.get("paper_pos")

def _save_paper_pos(state: dict, state_file: str, pos: dict | None):
    if pos is None:
        state["paper_pos"] = None
    else:
        state["paper_pos"] = pos
    save_state(state_file, state)

def main():
    with open("config/config.yaml", "r") as f:
        cfg = yaml.safe_load(f)

    ex = create_exchange(cfg["mode"]["testnet"])
    symbol = cfg["exchange"]["symbol"]

    # live일 때만 레버리지/마진 설정
    if cfg["mode"]["live"]:
        setup_leverage_and_mode(ex, symbol, cfg["exchange"]["leverage"], cfg["exchange"]["margin_mode"])

    state_file = cfg["storage"]["state_file"]
    state = load_state(state_file)

    # 전략 로더(커스텀 교체 가능)
    gen = load_strategy(cfg["strategy"].get("strategy_loader", "src.strategy"))

    while True:
        now = datetime.now(timezone.utc)
        if cfg["runtime"]["align_to_candle"] and now.minute % 15 != 0:
            nxt = next_quarter_minute(now)
            time.sleep(max((nxt - now).total_seconds(), 1))
            continue

        # 데이터 수집
        try:
            from .strategy import fetch_ohlcv  # 재사용
            df15 = fetch_ohlcv(ex, symbol, cfg["strategy"]["base_tf"], limit=600)
            df1h = fetch_ohlcv(ex, symbol, cfg["strategy"]["htf"], limit=600)
            price = float(df15["close"].iloc[-1])
        except Exception as e:
            notify(f"[ERR] OHLCV fetch 실패: {e}")
            time.sleep(5)
            continue

        # 일손실 가드
        equity_now = fetch_equity_usdt(ex) if cfg["mode"]["live"] else 10000.0
        state = ensure_daily_baseline(state, state_file, equity_now, cfg["runtime"]["kst_tz"])
        can_trade, dd = daily_dd_ok(state, equity_now, cfg["risk"]["max_daily_dd"])
        if not can_trade:
            notify(f"[가드] 일손실 한도 도달({dd:.2%}). 오늘 거래 중지.")
            time.sleep(60)
            continue

        # 신호 계산
        try:
            signal = gen(df15.copy(), df1h.copy(), cfg)
        except Exception as e:
            notify(f"[ERR] 신호 계산 실패: {e}")
            signal = None

        # 포지션 조회(live일 때만)
        if cfg["mode"]["live"]:
            qty_open, pos_side = get_position_qty_side(ex, symbol)
        else:
            qty_open, pos_side = 0.0, "flat"

        ts = now.astimezone().strftime("%Y-%m-%d %H:%M")

        # 거래 시간/펀딩 회피(옵션)
        trade_win = tuple(cfg["strategy"].get("trade_window_kst", ["00:00","23:59"]))
        ok_time = in_trade_window_kst(now, trade_win, cfg["runtime"]["kst_tz"])
        avoid_min = int(cfg["strategy"].get("avoid_funding_minutes", 0))
        ok_funding = (avoid_min <= 0) or (not near_funding_window(now, avoid_min))
        if not ok_time or not ok_funding:
            reason = "시간외" if not ok_time else "펀딩근접"
            notify(f"[{ts}] 신호:{signal or '없음'} | {reason} 스킵 | 가격:{price:.2f}")
            nxt = next_quarter_minute()
            time.sleep(max((nxt - datetime.now(timezone.utc)).total_seconds(), 1))
            continue

        # 페이퍼 포지션 상태 로드
        paper_pos = _load_paper_pos(state) if not cfg["mode"]["live"] else None

        # 페이퍼 포지션 청산 체크
        if not cfg["mode"]["live"] and paper_pos:
            side_p = paper_pos["side"]
            entry  = float(paper_pos["entry"])
            stop   = float(paper_pos["stop"])
            tp     = float(paper_pos["tp"])
            qty_p  = float(paper_pos["qty"])

            hit_sl = (price <= stop) if side_p == "LONG" else (price >= stop)
            hit_tp = (price >= tp)   if side_p == "LONG" else (price <= tp)

            if hit_sl or hit_tp:
                exit_px = stop if hit_sl else tp
                pnl = (exit_px - entry) * qty_p if side_p == "LONG" else (entry - exit_px) * qty_p
                fee_rate = float(cfg["exchange"].get("fee_rate", 0.0004))
                fees = (entry * qty_p + exit_px * qty_p) * fee_rate
                pnl -= fees

                notify(f"[페이퍼-청산] {symbol} {side_p} @ {entry:.2f} → {exit_px:.2f} | PnL={pnl:.4f} | 이유={'TP' if hit_tp else 'SL'}")
                _save_paper_pos(state, state_file, None)

                nxt = next_quarter_minute()
                time.sleep(max((nxt - datetime.now(timezone.utc)).total_seconds(), 1))
                continue

        # 진입 처리
        if signal and ((pos_side == "flat") and (paper_pos is None if not cfg["mode"]["live"] else True)):
            qty, stop = calc_qty_by_risk(df15, cfg, entry_price=price, side=signal, equity=equity_now)
            if qty <= 0:
                notify(f"[{ts}] 신호 {signal} 발생했지만 수량=0. 스킵.")
            else:
                if not cfg["mode"]["live"]:
                    tp_pct = float(cfg["strategy"]["take_profit_percent"])
                    tp = _compute_tp_by_percent(price, signal, tp_pct)
                    rec = {"side": signal, "entry": price, "stop": stop, "tp": tp, "qty": qty, "time": ts}
                    _save_paper_pos(state, state_file, rec)
                    notify(f"[페이퍼-진입] {symbol} {signal} qty={qty:.6f} @ {price:.2f} | SL={stop:.2f} | TP={tp:.2f}")
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
