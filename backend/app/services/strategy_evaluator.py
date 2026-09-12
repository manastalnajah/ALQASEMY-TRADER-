from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session
from app.strategies.strategy_manager import manager as strategy_manager
from app.services import trade_service
from app.domain import schemas
from app.logging.logger import system_logger
from app.config import config
from app.indicators.atr import calculate_atr


def _price(market_data: dict) -> float:
    return float(market_data.get("close") or market_data.get("price") or 0.0)


def _build_protection(market_data: dict, decision: str, entry: float, sl: float, tp: float):
    if sl > 0 and tp > 0:
        return sl, tp
    atr = float(market_data.get("atr") or 0.0)
    if atr <= 0:
        return 0.0, 0.0
    risk_distance = atr * config.atr_sl_multiplier
    if decision.startswith("BUY"):
        return entry - risk_distance, entry + (risk_distance * config.reward_risk)
    if decision.startswith("SELL"):
        return entry + risk_distance, entry - (risk_distance * config.reward_risk)
    return 0.0, 0.0


def evaluate_and_execute_strategy(db: Session, strategy_name: str, market_data: dict):
    symbol = str(market_data.get("symbol") or "").upper()
    timeframe = str(market_data.get("timeframe") or config.timeframe).upper()
    candle_key = str(market_data.get("candle_key") or market_data.get("open_time") or "")
    if not symbol or not candle_key:
        return {"status": "ignored", "decision": "HOLD", "message": "Missing symbol/candle identity"}

    if strategy_name == "smart_limits" and not config.allow_smart_limits:
        return {"status": "ignored", "decision": "HOLD", "message": "Smart limits disabled"}
    if strategy_name == "scalping" and not config.allow_scalping:
        return {"status": "ignored", "decision": "HOLD", "message": "Scalping disabled"}

    result = strategy_manager.execute(strategy_name, market_data)
    if isinstance(result, dict):
        decision = str(result.get("decision", "HOLD")).upper()
        entry = float(result.get("entry_price", 0.0) or 0.0)
        sl = float(result.get("sl", 0.0) or 0.0)
        tp = float(result.get("tp", 0.0) or 0.0)
    else:
        decision = str(result).upper()
        entry, sl, tp = 0.0, 0.0, 0.0

    if decision == "HOLD":
        return {"status": "success", "decision": "HOLD"}

    current = _price(market_data)
    if entry <= 0:
        entry = current
    sl, tp = _build_protection(market_data, decision, entry, sl, tp)
    if sl <= 0 or tp <= 0:
        system_logger.warning("🛑 %s %s rejected: no valid SL/TP", strategy_name, symbol)
        return {"status": "blocked", "decision": "HOLD", "message": "No valid SL/TP"}

    # Ensure geometry is correct before the risk engine sees it.
    if decision.startswith("BUY") and not (sl < entry < tp):
        return {"status": "blocked", "decision": "HOLD", "message": "Invalid BUY protection geometry"}
    if decision.startswith("SELL") and not (tp < entry < sl):
        return {"status": "blocked", "decision": "HOLD", "message": "Invalid SELL protection geometry"}

    signal_key = f"{symbol}:{timeframe}:{strategy_name}:{candle_key}:{decision}"
    command = schemas.CommandCreate(
        symbol=symbol,
        order_type=decision,
        # Risk engine calculates the authoritative size. This is only a placeholder.
        lot_size=1.0,
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        strategy_name=strategy_name,
        signal_key=signal_key,
        ea_id=str(market_data.get("ea_id") or ""),
    )
    try:
        created = trade_service.process_new_command(db, command, enforce_risk=True)
    except Exception as exc:
        system_logger.warning("🛑 %s %s blocked: %s", strategy_name, symbol, exc)
        return {"status": "blocked", "decision": "HOLD", "message": str(exc)}

    return {
        "status": "success",
        "decision": decision,
        "symbol": symbol,
        "command_id": str(created.id),
        "lot_size": created.lot_size,
        "entry_price": created.entry_price,
        "stop_loss": created.stop_loss,
        "take_profit": created.take_profit,
    }
