from __future__ import annotations

import math
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import config
from app.logging.logger import system_logger

ACTIVE_STATUSES = ("pending", "processing")


def _utcnow() -> datetime:
    return datetime.utcnow()


def _round_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor((value / step) + 1e-12) * step


def _account(db: Session, account_id: str):
    """جلب الحساب بناءً على المعرف الفريد UUID وليس عشوائياً"""
    return db.execute(text("""
        SELECT id AS account_id, account_number, balance, equity, margin, free_margin, margin_level,
               is_connected, last_heartbeat, last_sync
        FROM trading_accounts
        WHERE id = :account_id
    """), {"account_id": account_id}).mappings().first()


def _fresh_account(db: Session, account_id: str):
    account = _account(db, account_id)
    if not account:
        return None, "NO_ACCOUNT"
    if not account["is_connected"]:
        return None, "ACCOUNT_DISCONNECTED"
    stamp = account.get("last_heartbeat") or account.get("last_sync")
    if stamp is None:
        return None, "ACCOUNT_TIMESTAMP_MISSING"
    if isinstance(stamp, str):
        try:
            stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None, "ACCOUNT_TIMESTAMP_INVALID"
    age = (_utcnow() - stamp).total_seconds()
    if age > config.account_stale_seconds:
        return None, f"ACCOUNT_STALE_{int(age)}S"
    return account, None


def _get_or_create_risk_state(db: Session, account_id: str, equity: float):
    """إدارة حالة المخاطر مخصصة لكل حساب وكل يوم تداول بناءً على قيود قاعدة البيانات الجديدة"""
    day_key = _utcnow().strftime("%Y-%m-%d")
    
    state = db.execute(text("""
        SELECT * FROM risk_state 
        WHERE account_id = :account_id AND day_key = :day_key 
        FOR UPDATE
    """), {"account_id": account_id, "day_key": day_key}).mappings().first()
    
    if not state:
        # إدراج حالة جديدة لهذا الحساب في هذا اليوم
        db.execute(text("""
            INSERT INTO risk_state (account_id, day_key, day_start_equity, high_water_equity, trading_halted, halt_reason, updated_at)
            VALUES (:account_id, :day_key, :equity, :equity, false, '', :now)
            ON CONFLICT (account_id, day_key) DO NOTHING
        """), {"account_id": account_id, "day_key": day_key, "equity": equity, "now": _utcnow()})
        return {"day_key": day_key, "day_start_equity": equity, "high_water_equity": equity, "trading_halted": False, "halt_reason": ""}

    high = max(float(state["high_water_equity"] or equity), equity)
    if high != float(state["high_water_equity"] or 0):
        db.execute(text("""
            UPDATE risk_state SET high_water_equity=:high, updated_at=:now 
            WHERE account_id=:account_id AND day_key=:day_key
        """), {"high": high, "now": _utcnow(), "account_id": account_id, "day_key": day_key})
        
    return dict(state, high_water_equity=high)


def _active_counts(db: Session, account_id: str, account_number: int, symbol: str):
    """فصل الأوامر والصفقات المعلقة بناءً على الحساب لمنع التداخل"""
    command_row = db.execute(text("""
        SELECT COUNT(*) AS pending
        FROM trade_commands
        WHERE account_id=:account_id AND symbol=:symbol AND status IN ('pending','processing')
    """), {"account_id": account_id, "symbol": symbol}).mappings().first()
    
    live_pending = db.execute(text("""
        SELECT COUNT(*) AS pending
        FROM pending_orders WHERE account_number=:account_number AND symbol=:symbol
    """), {"account_number": account_number, "symbol": symbol}).mappings().first()
    
    return int(command_row["pending"] or 0) + int(live_pending["pending"] or 0)


def _symbol_spec(db: Session, symbol: str):
    return db.execute(text("""
        SELECT symbol, digits, point, tick_size, tick_value,
               volume_min, volume_max, volume_step, stops_level_points, contract_size
        FROM symbol_specs WHERE symbol=:symbol
    """), {"symbol": symbol}).mappings().first()


def calculate_position_size(equity: float, risk_pct: float, entry: float, stop: float, spec) -> float:
    if equity <= 0 or risk_pct <= 0 or entry <= 0 or stop <= 0 or not spec:
        return 0.0
    def v(key):
        try:
            return spec[key]
        except (TypeError, KeyError):
            return getattr(spec, key)
            
    distance = abs(entry - stop)
    tick_size = float(v("tick_size"))
    tick_value = float(v("tick_value"))
    
    if distance <= 0 or tick_size <= 0 or tick_value <= 0:
        return 0.0
        
    loss_per_lot = (distance / tick_size) * tick_value
    if loss_per_lot <= 0:
        return 0.0
        
    risk_money = equity * (risk_pct / 100.0)
    raw = risk_money / loss_per_lot
    step = float(v("volume_step"))
    minimum = float(v("volume_min"))
    maximum = float(v("volume_max"))
    
    lot = _round_step(raw, step)
    if lot < minimum:
        return 0.0
    return min(lot, maximum)


def validate_and_size(db: Session, *, account_id: str, symbol: str, order_type: str, entry: float, stop: float, target: float, signal_key: str):
    symbol = symbol.upper()
    order_type = order_type.upper()
    
    # دعم أوامر الإيقاف لتطابق EA v14.0
    if order_type not in {"BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}:
        return None, "INVALID_ORDER_TYPE"
    if entry <= 0 or stop <= 0 or target <= 0:
        return None, "SL_TP_REQUIRED"

    # عزل قفل التزامن ليكون مخصصاً لكل حساب ورمز معاً لتجنب حظر حسابات أخرى
    lock_key = f"ALQASEMY:{account_id}:{symbol}"
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": lock_key})

    # التحقق من التكرار داخل نفس الحساب
    duplicate = db.execute(text("""
        SELECT id FROM trade_commands
        WHERE account_id=:account_id
          AND symbol=:symbol
          AND order_type=:order_type
          AND status IN ('pending','processing')
          AND ABS(COALESCE(entry_price,0) - :entry) < :epsilon
        LIMIT 1
    """), {"account_id": account_id, "symbol": symbol, "order_type": order_type, "entry": entry, "epsilon": max(abs(entry) * 1e-6, 1e-8)}).first()
    if duplicate:
        return None, "DUPLICATE_ACTIVE_COMMAND"

    recent = db.execute(text("""
        SELECT id FROM trade_commands
        WHERE account_id=:account_id 
          AND symbol=:symbol AND status NOT IN ('cancelled','expired','failed')
          AND created_at >= NOW() - (:minutes * INTERVAL '1 minute')
          AND COALESCE(signal_key,'') = :signal_key
        LIMIT 1
    """), {"account_id": account_id, "symbol": symbol, "minutes": config.signal_cooldown_minutes, "signal_key": signal_key}).first()
    if recent:
        return None, "DUPLICATE_SIGNAL"

    account, reason = _fresh_account(db, account_id)
    if not account:
        return None, reason
        
    equity = float(account["equity"] or 0)
    balance = float(account["balance"] or 0)
    margin_level = float(account["margin_level"] or 0)
    margin = float(account["margin"] or 0)
    account_number = account["account_number"]
    
    if equity <= 0 or balance <= 0:
        return None, "INVALID_ACCOUNT_EQUITY"
    if margin_level and margin_level < config.min_margin_level_pct:
        return None, "LOW_MARGIN_LEVEL"
    if margin > 0 and ((margin / equity) * 100.0) > config.max_margin_usage_pct:
        return None, "HIGH_MARGIN_USAGE"

    state = _get_or_create_risk_state(db, account_id, equity)
    if state["trading_halted"]:
        return None, f"RISK_HALTED:{state['halt_reason']}"

    daily_loss_pct = max(0.0, (float(state["day_start_equity"]) - equity) / float(state["day_start_equity"]) * 100.0) if state["day_start_equity"] else 0.0
    drawdown_pct = max(0.0, (float(state["high_water_equity"]) - equity) / float(state["high_water_equity"]) * 100.0) if state["high_water_equity"] else 0.0
    
    if daily_loss_pct >= config.max_daily_loss_pct:
        db.execute(text("""
            UPDATE risk_state SET trading_halted=true, halt_reason=:reason, updated_at=:now 
            WHERE account_id=:account_id AND day_key=:day_key
        """), {"reason": "DAILY_LOSS_LIMIT", "now": _utcnow(), "account_id": account_id, "day_key": state["day_key"]})
        return None, "DAILY_LOSS_LIMIT"
        
    if drawdown_pct >= config.max_drawdown_pct:
        db.execute(text("""
            UPDATE risk_state SET trading_halted=true, halt_reason=:reason, updated_at=:now 
            WHERE account_id=:account_id AND day_key=:day_key
        """), {"reason": "MAX_DRAWDOWN", "now": _utcnow(), "account_id": account_id, "day_key": state["day_key"]})
        return None, "MAX_DRAWDOWN"

    snapshot = db.execute(text("SELECT last_sync FROM position_snapshots WHERE account_number=:account"), {"account": account_number}).first()
    if not snapshot:
        return None, "POSITION_SNAPSHOT_MISSING"
    snap = snapshot[0]
    if isinstance(snap, str):
        snap = datetime.fromisoformat(snap.replace("Z", "+00:00")).replace(tzinfo=None)
    if (_utcnow() - snap).total_seconds() > config.account_stale_seconds:
        return None, "POSITION_SNAPSHOT_STALE"

    counts = db.execute(text("""
        SELECT COUNT(*) AS total
        FROM live_positions WHERE account_number=:account
    """), {"account": account_number}).mappings().first()
    
    symbol_counts = db.execute(text("""
        SELECT COALESCE(SUM(volume),0) AS symbol_volume
        FROM live_positions WHERE account_number=:account AND symbol=:symbol
    """), {"account": account_number, "symbol": symbol}).mappings().first()
    
    open_total = int(counts["total"] or 0)
    symbol_exposure = float(symbol_counts["symbol_volume"] or 0)
    if open_total >= config.max_open_positions:
        return None, "MAX_OPEN_POSITIONS"
    if symbol_exposure >= config.max_symbol_exposure_lots:
        return None, "MAX_SYMBOL_EXPOSURE"

    pending = _active_counts(db, account_id, account_number, symbol)
    if pending >= config.max_pending_orders:
        return None, "MAX_PENDING_ORDERS"

    spec = _symbol_spec(db, symbol)
    if not spec:
        return None, "SYMBOL_SPEC_MISSING"

    lot = calculate_position_size(equity, config.risk_per_trade_pct, entry, stop, spec)
    if lot <= 0:
        return None, "RISK_TOO_SMALL_FOR_SYMBOL_MIN_LOT"
        
    max_additional = max(0.0, config.max_symbol_exposure_lots - symbol_exposure)
    if lot > max_additional:
        lot = _round_step(max_additional, float(spec["volume_step"]))
    if lot < float(spec["volume_min"]):
        return None, "EXPOSURE_LIMIT_BELOW_MIN_LOT"

    distance_points = abs(entry - stop) / float(spec["point"])
    min_stops = int(spec["stops_level_points"] or 0)
    if distance_points < min_stops:
        return None, "STOP_TOO_CLOSE"

    return {"lot_size": lot, "equity": equity, "account_number": account_number}, None
