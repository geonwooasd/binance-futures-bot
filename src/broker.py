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
