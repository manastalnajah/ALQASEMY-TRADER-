import logging
from typing import List, Optional
from fastapi import APIRouter, Header, HTTPException, BackgroundTasks
from sqlalchemy import text

from database import SessionLocal
from app.config import config
from app.domain import schemas
from app.services.strategy_evaluator import evaluate_and_execute_strategy

logger = logging.getLogger("mt5_router")

router = APIRouter(prefix="/api/v1/mt5", tags=["MT5 Gateway"])


def _authorize(x_mt5_key: Optional[str]):
    """التحقق من صحة مفتاح التواصل القادم من MT5/Cloudzy"""
    if config.require_control_api_key:
        valid_keys = [
            k for k in [
                getattr(config, "mt5_api_key", None),
                getattr(config, "control_api_key", None),
                "AlqasemyTrader2026_SecureKey!@"
            ] if k
        ]
        if not x_mt5_key or x_mt5_key not in valid_keys:
            raise HTTPException(401, "Invalid or missing MT5 authentication key")


def run_strategy_in_background(symbol: str, timeframe: str, latest_candle: schemas.CandleItem, ea_id: str):
    db = SessionLocal()
    try:
        bot_state_record = db.execute(
            text("SELECT is_running FROM bot_state WHERE id = 1 LIMIT 1")
        ).mappings().first()

        if bot_state_record and not bot_state_record["is_running"]:
            return

        account = db.execute(
            text("""
                SELECT id, account_number, balance, equity, currency 
                FROM trading_accounts 
                WHERE ea_id = :ea_id AND is_active = true AND is_trade_allowed = true
                ORDER BY updated_at DESC LIMIT 1
            """),
            {"ea_id": ea_id}
        ).mappings().first()

        if not account:
            account = db.execute(
                text("""
                    SELECT id, account_number, balance, equity, currency 
                    FROM trading_accounts 
                    WHERE is_active = true AND is_trade_allowed = true
                    ORDER BY updated_at DESC LIMIT 1
                """)
            ).mappings().first()

        if not account:
            return

        account_id = str(account["id"])

        spec = db.execute(
            text("SELECT tick_size, tick_value, point, digits FROM symbol_specs WHERE symbol = :sym LIMIT 1"),
            {"sym": symbol}
        ).mappings().first()

        tick_size = float(spec["tick_size"]) if spec and spec.get("tick_size") else (0.01 if "XAU" in symbol else 0.00001)
        tick_value = float(spec["tick_value"]) if spec and spec.get("tick_value") else 1.0

        market_data = {
            "symbol": symbol,
            "timeframe": timeframe,
            "open_time": str(latest_candle.open_time),
            "open": float(latest_candle.open),
            "high": float(latest_candle.high),
            "low": float(latest_candle.low),
            "close": float(latest_candle.close),
            "volume": float(latest_candle.volume),
            "balance": float(account["balance"] or 10000.0),
            "equity": float(account["equity"] or 10000.0),
            "tick_size": tick_size,
            "tick_value": tick_value,
            "ea_id": ea_id,
            "candle_key": str(latest_candle.open_time),
        }

        strategy_to_run = getattr(config, "default_strategy", "golden_setup")

        result = evaluate_and_execute_strategy(
            db=db,
            account_id=account_id,
            strategy_name=strategy_to_run,
            market_data=market_data,
        )

        decision = result.get("decision", "HOLD")
        if decision != "HOLD":
            logger.info(f"🎯 Signal: {decision} on {symbol} | Account: {account['account_number']}")

    except Exception as e:
        logger.exception(f"❌ Strategy Execution error: {e}")
    finally:
        db.close()


# ─── إزالة async لتمكين الـ Multithreading والقضاء على الـ Timeouts (5203) ───

@router.post("/account/sync")
def sync_account(
    account_data: schemas.AccountHeartbeat, 
    x_mt5_key: Optional[str] = Header(default=None)
):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        margin_level = account_data.margin_level if account_data.margin_level is not None else (
            account_data.equity / account_data.margin * 100 if account_data.margin > 0 else 0
        )
        server_name = account_data.server or "unknown"

        result = db.execute(text("""
            UPDATE trading_accounts 
            SET balance = CAST(:balance AS NUMERIC),
                equity = CAST(:equity AS NUMERIC),
                margin = CAST(:margin AS NUMERIC),
                free_margin = CAST(:free_margin AS NUMERIC),
                profit = CAST(:profit AS NUMERIC),
                margin_level = CAST(:margin_level AS NUMERIC),
                is_connected = :connected,
                is_active = true,
                server = CASE WHEN server IS NULL OR server = '' OR server = 'unknown' THEN :server ELSE server END,
                currency = COALESCE(:currency, currency),
                leverage = COALESCE(:leverage, leverage),
                ea_id = COALESCE(NULLIF(:ea_id, ''), ea_id),
                ea_version = COALESCE(NULLIF(:ea_version, ''), ea_version),
                last_sync = NOW(),
                last_heartbeat = NOW(),
                updated_at = NOW()
            WHERE account_number = CAST(:account AS BIGINT)
            RETURNING id
        """), {
            "balance": account_data.balance,
            "equity": account_data.equity,
            "margin": account_data.margin,
            "free_margin": account_data.free_margin,
            "profit": account_data.profit,
            "margin_level": margin_level,
            "connected": account_data.is_connected,
            "server": server_name,
            "currency": account_data.currency,
            "leverage": account_data.leverage,
            "ea_id": account_data.ea_id or "",
            "ea_version": account_data.ea_version or "",
            "account": account_data.account_number,
        }).first()

        if not result:
            db.execute(text("""
                INSERT INTO trading_accounts(
                    account_number, server, balance, equity, margin, free_margin, 
                    profit, margin_level, is_connected, is_active, is_trade_allowed,
                    currency, leverage, ea_id, ea_version, last_sync, last_heartbeat, created_at, updated_at
                )
                VALUES(
                    CAST(:account AS BIGINT), :server, CAST(:balance AS NUMERIC), CAST(:equity AS NUMERIC), 
                    CAST(:margin AS NUMERIC), CAST(:free_margin AS NUMERIC), CAST(:profit AS NUMERIC), 
                    CAST(:margin_level AS NUMERIC), :connected, true, true,
                    COALESCE(:currency, 'USD'), COALESCE(:leverage, 500), :ea_id, :ea_version,
                    NOW(), NOW(), NOW(), NOW()
                )
            """), {
                "account": account_data.account_number,
                "server": server_name,
                "balance": account_data.balance,
                "equity": account_data.equity,
                "margin": account_data.margin,
                "free_margin": account_data.free_margin,
                "profit": account_data.profit,
                "margin_level": margin_level,
                "connected": account_data.is_connected,
                "currency": account_data.currency,
                "leverage": account_data.leverage,
                "ea_id": account_data.ea_id or "",
                "ea_version": account_data.ea_version or ""
            })
        db.commit()
        return {"status": "success", "account_number": account_data.account_number}
    except Exception as exc:
        db.rollback()
        logger.exception("Account sync failed: %s", exc)
        raise HTTPException(500, "Account synchronization failed")
    finally:
        db.close()


@router.post("/heartbeat")
def account_heartbeat(
    account_data: schemas.AccountHeartbeat, 
    x_mt5_key: Optional[str] = Header(default=None)
):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        margin_level = account_data.margin_level if account_data.margin_level is not None else (
            account_data.equity / account_data.margin * 100 if account_data.margin > 0 else 0
        )
        db.execute(text("""
            UPDATE trading_accounts 
            SET balance = CAST(:balance AS NUMERIC),
                equity = CAST(:equity AS NUMERIC),
                margin = CAST(:margin AS NUMERIC),
                free_margin = CAST(:free_margin AS NUMERIC),
                profit = CAST(:profit AS NUMERIC),
                margin_level = CAST(:margin_level AS NUMERIC),
                is_connected = :connected,
                is_active = true,
                ea_id = COALESCE(NULLIF(:ea_id, ''), ea_id),
                ea_version = COALESCE(NULLIF(:ea_version, ''), ea_version),
                last_heartbeat = NOW(),
                last_sync = NOW(),
                updated_at = NOW()
            WHERE account_number = CAST(:account AS BIGINT)
        """), {
            "balance": account_data.balance,
            "equity": account_data.equity,
            "margin": account_data.margin,
            "free_margin": account_data.free_margin,
            "profit": account_data.profit,
            "margin_level": margin_level,
            "connected": account_data.is_connected,
            "ea_id": account_data.ea_id or "",
            "ea_version": account_data.ea_version or "",
            "account": account_data.account_number
        })
        db.commit()
        return {"status": "success", "account_number": account_data.account_number}
    finally:
        db.close()


@router.post("/candles/sync")
def sync_candles(
    req: schemas.CandlesSyncRequest,
    background_tasks: BackgroundTasks,
    x_mt5_key: Optional[str] = Header(default=None)
):
    _authorize(x_mt5_key)
    if not req.candles:
        return {"status": "ignored", "count": 0}

    db = SessionLocal()
    try:
        parameters = [{
            "sym": req.symbol,
            "tf": req.timeframe,
            "ot": candle.open_time,
            "o": candle.open,
            "h": candle.high,
            "l": candle.low,
            "c": candle.close,
            "v": candle.volume
        } for candle in req.candles]

        db.execute(text("""
            INSERT INTO candles (symbol_name, timeframe, open_time, open, high, low, close, volume, created_at)
            VALUES (:sym, :tf, :ot, :o, :h, :l, :c, :v, NOW())
            ON CONFLICT (symbol_name, timeframe, open_time) 
            DO UPDATE SET 
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume
        """), parameters)
        db.commit()

        latest = req.candles[-1]
        background_tasks.add_task(
            run_strategy_in_background,
            symbol=req.symbol,
            timeframe=req.timeframe,
            latest_candle=latest,
            ea_id=req.ea_id or "MT5-ALQASEMY-01"
        )
        return {"status": "success", "count": len(req.candles)}
    finally:
        db.close()


@router.get("/candles/status")
def check_candles_status(
    symbol: str,
    timeframe: str,
    x_mt5_key: Optional[str] = Header(default=None)
):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT COUNT(*) AS total, MAX(open_time) AS latest 
            FROM candles 
            WHERE symbol_name = :sym AND timeframe = :tf
        """), {"sym": symbol, "tf": timeframe}).mappings().first()

        total = row["total"] if row else 0
        latest = row["latest"] if row else None
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": total,
            "latest_candle": str(latest) if latest else None,
            "ready": total >= 200
        }
    finally:
        db.close()


@router.post("/positions/sync")
def sync_positions(
    req: schemas.PositionsSyncRequest,
    x_mt5_key: Optional[str] = Header(default=None)
):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        db.execute(text("TRUNCATE TABLE open_positions"))
        for pos in req.positions:
            db.execute(text("""
                INSERT INTO open_positions (ticket, symbol, position_type, volume, open_price, current_price, sl, tp, profit, open_time, updated_at)
                VALUES (:ticket, :sym, :type, :vol, :open_p, :curr_p, :sl, :tp, :profit, :open_time, NOW())
            """), {
                "ticket": pos.ticket,
                "sym": pos.symbol,
                "type": pos.side,
                "vol": pos.volume,
                "open_p": pos.price_open,
                "curr_p": pos.price_open,
                "sl": pos.stop_loss,
                "tp": pos.take_profit,
                "profit": pos.profit,
                "open_time": pos.updated_at or text("NOW()"),
            })
        db.commit()
        return {"status": "success", "count": len(req.positions)}
    finally:
        db.close()


@router.post("/pending-orders/sync")
def sync_pending_orders(
    req: schemas.PendingOrdersSyncRequest,
    x_mt5_key: Optional[str] = Header(default=None)
):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        db.execute(text("TRUNCATE TABLE pending_orders"))
        for o in req.orders:
            db.execute(text("""
                INSERT INTO pending_orders (ticket, symbol, order_type, volume, price, sl, tp, open_time, updated_at)
                VALUES (:ticket, :sym, :type, :vol, :price, :sl, :tp, :open_time, NOW())
            """), {
                "ticket": o.ticket,
                "sym": o.symbol,
                "type": o.side,
                "vol": o.volume,
                "price": o.price_open,
                "sl": o.stop_loss,
                "tp": o.take_profit,
                "open_time": o.updated_at or text("NOW()"),
            })
        db.commit()
        return {"status": "success", "count": len(req.orders)}
    finally:
        db.close()


@router.post("/specs/sync")
def sync_symbol_specs(
    specs_data: List[dict],
    x_mt5_key: Optional[str] = Header(default=None)
):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        count = 0
        for s in specs_data:
            symbol = str(s.get("symbol", ""))
            if not symbol: continue
                
            point = float(s.get("point", 0.00001))
            digits = int(s.get("digits", 5))
            spread = int(s.get("spread", 0))
            
            tick_value = float(s.get("tick_value", 1.0))
            tick_size = float(s.get("tick_size", 0.00001))
            contract_size = float(s.get("contract_size", 100000.0))
            
            min_lot = float(s.get("min_lot") or s.get("volume_min") or 0.01)
            max_lot = float(s.get("max_lot") or s.get("volume_max") or 100.0)
            lot_step = float(s.get("lot_step") or s.get("volume_step") or 0.01)

            db.execute(text("""
                INSERT INTO symbol_specs (symbol, point, digits, spread, tick_value, tick_size, contract_size, min_lot, max_lot, lot_step, updated_at)
                VALUES (:sym, :point, :digits, :spread, :tv, :ts, :cs, :min_l, :max_l, :step, NOW())
                ON CONFLICT (symbol) DO UPDATE SET
                    point = EXCLUDED.point,
                    digits = EXCLUDED.digits,
                    spread = EXCLUDED.spread,
                    tick_value = EXCLUDED.tick_value,
                    tick_size = EXCLUDED.tick_size,
                    contract_size = EXCLUDED.contract_size,
                    min_lot = EXCLUDED.min_lot,
                    max_lot = EXCLUDED.max_lot,
                    lot_step = EXCLUDED.lot_step,
                    updated_at = NOW()
            """), {
                "sym": symbol,
                "point": point,
                "digits": digits,
                "spread": spread,
                "tv": tick_value,
                "ts": tick_size,
                "cs": contract_size,
                "min_l": min_lot,
                "max_l": max_lot,
                "step": lot_step,
            })
            count += 1
            
        db.commit()
        return {"status": "success", "count": count}
    finally:
        db.close()


@router.get("/commands")
def get_pending_commands(
    limit: int = 10,
    ea_id: Optional[str] = None,
    x_mt5_key: Optional[str] = Header(default=None)
):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        rows = db.execute(text("""
            SELECT id, symbol, order_type, lot_size, entry_price, stop_loss, take_profit, ea_id, strategy_name, signal_key, created_at
            FROM trade_commands
            WHERE status = 'pending'
              AND (CAST(:ea_id AS TEXT) IS NULL OR ea_id = '' OR ea_id = CAST(:ea_id AS TEXT))
            ORDER BY created_at ASC
            LIMIT :limit
        """), {"ea_id": ea_id, "limit": limit}).mappings().all()

        commands = []
        for r in rows:
            commands.append({
                "id": str(r["id"]),
                "command_id": str(r["id"]),
                "symbol": r["symbol"],
                "order_type": r["order_type"],
                "side": r["order_type"],
                "volume": float(r["lot_size"]),
                "entry_price": float(r["entry_price"]) if r["entry_price"] else 0.0,
                "sl": float(r["stop_loss"]) if r["stop_loss"] else 0.0,
                "tp": float(r["take_profit"]) if r["take_profit"] else 0.0,
                "status": "pending",
                "strategy_name": r["strategy_name"] or "",
                "signal_key": r["signal_key"] or "",
                "created_at": r["created_at"].isoformat() if r["created_at"] else "",
                "ea_id": r["ea_id"] or ""
            })
        return commands
    finally:
        db.close()


@router.post("/reports")
def report_execution(
    reports: List[schemas.CommandReportRequest],
    x_mt5_key: Optional[str] = Header(default=None)
):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        for rep in reports:
            ticket = rep.mt5_ticket or rep.mt5_order_ticket or rep.mt5_deal_ticket
            db.execute(text("""
                UPDATE trade_commands
                SET status = :status,
                    ticket = :ticket,
                    error_message = :err,
                    executed_at = NOW()
                WHERE id = CAST(:cmd_id AS UUID)
            """), {
                "status": rep.status,
                "ticket": ticket,
                "err": rep.error_message or "",
                "cmd_id": rep.command_id if hasattr(rep, "command_id") else None
            })
        db.commit()
        return {"status": "success", "count": len(reports)}
    finally:
        db.close()
