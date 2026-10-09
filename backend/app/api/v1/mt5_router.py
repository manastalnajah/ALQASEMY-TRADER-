# ============================================================
# app/api/mt5_router.py
# النسخة النهائية — V2.1
# ------------------------------------------------------------
# تدعم:
# - مزامنة آمنة للحسابات المتعددة (بدون TRUNCATE)
# - Smart Position Management (polling/ack/report)
# - حفظ current_price الحقيقي من EA
# - منع ACK وهمي عبر RETURNING id
# - إصلاح حذف الصفقات بـ != ALL(:tickets)
# ============================================================

import logging
from typing import List, Optional
from datetime import datetime, timezone

from fastapi import (
    APIRouter, Header, HTTPException, BackgroundTasks,
    Request, Depends, Query,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from database import AsyncSessionLocal, get_db
from app.config import config
from app.domain import schemas
from app.services.strategy_evaluator import evaluate_and_execute_strategy
from app.repositories.trade_repo import TradeRepository
from app.repositories.position_command_repo import PositionCommandRepository
from app.services import trade_service


logger = logging.getLogger("mt5_router")

router = APIRouter(prefix="/api/v1/mt5", tags=["MT5 Gateway"])


# =====================================================================
# نماذج داخلية
# =====================================================================
class CommandAck(BaseModel):
    ea_id: Optional[str] = None
    account_number: Optional[int] = None


class CommandReport(BaseModel):
    status: str
    mt5_ticket: Optional[int] = 0
    mt5_order_ticket: Optional[int] = 0
    mt5_deal_ticket: Optional[int] = 0
    fill_price: Optional[float] = 0.0
    executed_volume: Optional[float] = 0.0
    mt5_retcode: Optional[int] = 0
    error_message: Optional[str] = ""
    ea_id: Optional[str] = ""
    account_number: Optional[int] = 0
    command_id: Optional[str] = ""


class PositionCommandAck(BaseModel):
    ea_id: Optional[str] = None
    account_number: Optional[int] = None


class PositionCommandReport(BaseModel):
    status: str
    position_ticket: int
    executed_sl: Optional[float] = None
    executed_tp: Optional[float] = None
    executed_volume: Optional[float] = None
    mt5_retcode: Optional[int] = None
    error_message: Optional[str] = None
    ea_id: Optional[str] = ""
    account_number: Optional[int] = None


# =====================================================================
# Auth
# =====================================================================

def _authorize(x_mt5_key: Optional[str]):
    """
    التحقق من مفتاح MT5.

    ⚠️ ملاحظة أمنية: لا يوجد مفتاح ثابت مُضمَّن في الكود.
    المفتاح يجب أن يكون في config (بيئة الإنتاج).
    """
    if config.require_control_api_key:
        valid_keys = [
            k for k in [
                getattr(config, "mt5_api_key", None),
                getattr(config, "control_api_key", None),
            ] if k
        ]
        if not valid_keys:
            raise HTTPException(500, "Server misconfigured: no API key set")
        if not x_mt5_key or x_mt5_key not in valid_keys:
            raise HTTPException(401, "Invalid or missing MT5 authentication key")


# =====================================================================
# Background strategy runner
# =====================================================================

async def run_strategy_in_background(
    symbol: str,
    timeframe: str,
    latest_candle: schemas.CandleItem,
    ea_id: str,
):
    """
    تشغيل الاستراتيجية في الخلفية بعد مزامنة الشموع.

    ⚠️ لا يوجد fallback "أحدث حساب نشط" لأنه قد يختار
    حسابًا غير مرتبط بالـ EA. نعتمد على ea_id فقط.
    """
    async with AsyncSessionLocal() as db:
        try:
            # فحص حالة البوت
            bot_state = (await db.execute(
                text("SELECT is_running FROM bot_state WHERE id = 1 LIMIT 1")
            )).mappings().first()

            if bot_state and not bot_state["is_running"]:
                return

            # جلب الحساب المرتبط بالـ ea_id فقط (بدون fallback)
            account = (await db.execute(
                text("""
                    SELECT id, account_number, balance, equity, currency
                    FROM trading_accounts
                    WHERE ea_id = :ea_id
                      AND is_active = true
                      AND is_trade_allowed = true
                    ORDER BY updated_at DESC
                    LIMIT 1
                """),
                {"ea_id": ea_id},
            )).mappings().first()

            if not account:
                logger.warning(
                    "⚠️ Strategy skipped: no active account for ea_id=%s",
                    ea_id,
                )
                return

            account_id = str(account["id"])
            real_balance = float(account["balance"] or 0.0)
            real_equity = float(account["equity"] or 0.0)

            if real_balance <= 0:
                logger.error(
                    "🛑 Balance<=0 for account %s — blocking strategy",
                    account["account_number"],
                )
                return

            # جلب مواصفات الرمز
            spec = (await db.execute(
                text("""
                    SELECT tick_size, tick_value, point, digits,
                           volume_min, volume_max, volume_step,
                           stops_level_points, freeze_level_points
                    FROM symbol_specs
                    WHERE symbol = :sym
                    LIMIT 1
                """),
                {"sym": symbol},
            )).mappings().first()

            tick_size = float(spec["tick_size"]) if spec and spec.get("tick_size") else (
                0.01 if "XAU" in symbol.upper() else 0.00001
            )
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
                "balance": real_balance,
                "equity": real_equity,
                "tick_size": tick_size,
                "tick_value": tick_value,
                "ea_id": ea_id,
                "account_number": int(account["account_number"]) or None,
                "candle_key": str(latest_candle.open_time),
            }

            strategy_to_run = getattr(config, "default_strategy", "golden_setup")

            result = await evaluate_and_execute_strategy(
                db=db,
                account_id=account_id,
                strategy_name=strategy_to_run,
                market_data=market_data,
            )

            decision = result.get("decision", "HOLD")
            if decision != "HOLD":
                logger.info(
                    "🎯 Signal: %s on %s | Account: %s",
                    decision, symbol, account["account_number"],
                )

        except Exception as exc:
            logger.exception("❌ Strategy execution error: %s", exc)


# =====================================================================
# 1. Account Sync
# =====================================================================

@router.post("/account/sync")
async def sync_account(
    account_data: schemas.AccountHeartbeat,
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    _authorize(x_mt5_key)
    try:
        margin_level = (
            account_data.margin_level
            if account_data.margin_level is not None
            else (
                account_data.equity / account_data.margin * 100
                if account_data.margin > 0 else 0
            )
        )
        server_name = account_data.server or "unknown"

        result = (await db.execute(text("""
            UPDATE trading_accounts
            SET balance = CAST(:balance AS NUMERIC),
                equity = CAST(:equity AS NUMERIC),
                margin = CAST(:margin AS NUMERIC),
                free_margin = CAST(:free_margin AS NUMERIC),
                profit = CAST(:profit AS NUMERIC),
                margin_level = CAST(:margin_level AS NUMERIC),
                is_connected = :connected,
                is_active = true,
                is_trade_allowed = :is_trade_allowed,
                server = CASE
                    WHEN server IS NULL OR server = '' OR server = 'unknown'
                    THEN :server ELSE server END,
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
            "is_trade_allowed": getattr(account_data, "is_trade_allowed", True),
            "server": server_name,
            "currency": account_data.currency,
            "leverage": account_data.leverage,
            "ea_id": account_data.ea_id or "",
            "ea_version": account_data.ea_version or "",
            "account": account_data.account_number,
        })).first()

        if not result:
            await db.execute(text("""
                INSERT INTO trading_accounts(
                    account_number, server, balance, equity, margin, free_margin,
                    profit, margin_level, is_connected, is_active, is_trade_allowed,
                    currency, leverage, ea_id, ea_version,
                    last_sync, last_heartbeat, created_at, updated_at
                )
                VALUES(
                    CAST(:account AS BIGINT), :server,
                    CAST(:balance AS NUMERIC), CAST(:equity AS NUMERIC),
                    CAST(:margin AS NUMERIC), CAST(:free_margin AS NUMERIC),
                    CAST(:profit AS NUMERIC), CAST(:margin_level AS NUMERIC),
                    :connected, true, :is_trade_allowed,
                    COALESCE(:currency, 'USD'), COALESCE(:leverage, 500),
                    :ea_id, :ea_version,
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
                "is_trade_allowed": getattr(account_data, "is_trade_allowed", True),
                "currency": account_data.currency,
                "leverage": account_data.leverage,
                "ea_id": account_data.ea_id or "",
                "ea_version": account_data.ea_version or "",
            })

        await db.commit()
        return {"status": "success", "account_number": account_data.account_number}

    except Exception as exc:
        await db.rollback()
        logger.exception("Account sync failed: %s", exc)
        raise HTTPException(500, "Account synchronization failed")


# =====================================================================
# 2. Heartbeat
# =====================================================================

@router.post("/heartbeat")
async def account_heartbeat(
    account_data: schemas.AccountHeartbeat,
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    _authorize(x_mt5_key)
    try:
        margin_level = (
            account_data.margin_level
            if account_data.margin_level is not None
            else (
                account_data.equity / account_data.margin * 100
                if account_data.margin > 0 else 0
            )
        )
        await db.execute(text("""
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
            "account": account_data.account_number,
        })
        await db.commit()
        return {"status": "success", "account_number": account_data.account_number}

    except Exception as exc:
        await db.rollback()
        raise HTTPException(500, "Heartbeat failed")


# =====================================================================
# 3. Candles Sync
# =====================================================================

async def process_candles_background_task(
    req: schemas.CandlesSyncRequest,
    ea_id: str,
):
    async with AsyncSessionLocal() as db:
        try:
            parameters = [{
                "sym": req.symbol,
                "tf": req.timeframe,
                "ot": candle.open_time,
                "o": candle.open,
                "h": candle.high,
                "l": candle.low,
                "c": candle.close,
                "v": candle.volume,
                "ic": getattr(candle, "is_closed", True),
            } for candle in req.candles]

            chunk_size = 100
            for i in range(0, len(parameters), chunk_size):
                chunk = parameters[i:i + chunk_size]
                await db.execute(text("""
                    INSERT INTO candles (
                        symbol_name, timeframe, open_time,
                        open, high, low, close, volume,
                        is_closed, created_at
                    )
                    VALUES (:sym, :tf, :ot, :o, :h, :l, :c, :v, :ic, NOW())
                    ON CONFLICT (symbol_name, timeframe, open_time)
                    DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        is_closed = EXCLUDED.is_closed
                """), chunk)
                await db.commit()

            latest = req.candles[-1]
            await run_strategy_in_background(
                symbol=req.symbol,
                timeframe=req.timeframe,
                latest_candle=latest,
                ea_id=ea_id,
            )

        except Exception as exc:
            await db.rollback()
            logger.exception("Background candles sync failed: %s", exc)


@router.post("/candles/sync")
async def sync_candles(
    req: schemas.CandlesSyncRequest,
    background_tasks: BackgroundTasks,
    x_mt5_key: Optional[str] = Header(default=None),
):
    _authorize(x_mt5_key)
    if not req.candles:
        return {"status": "ignored", "count": 0}

    ea_id = req.ea_id or "MT5-ALQASEMY-01"

    background_tasks.add_task(process_candles_background_task, req, ea_id)

    return {
        "status": "success",
        "count": len(req.candles),
        "message": "processing in background chunks",
    }


# =====================================================================
# 4. Candles Status
# =====================================================================

@router.get("/candles/status")
async def check_candles_status(
    symbol: str,
    timeframe: str,
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    _authorize(x_mt5_key)
    try:
        row = (await db.execute(text("""
            SELECT COUNT(*) AS total, MAX(open_time) AS latest
            FROM candles
            WHERE symbol_name = :sym AND timeframe = :tf
        """), {"sym": symbol, "tf": timeframe})).mappings().first()

        total = row["total"] if row else 0
        latest = row["latest"] if row else None

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": total,
            "latest_candle": str(latest) if latest else None,
            "last_open_time": str(latest) if latest else "",
            "ready": total >= 200,
        }

    except Exception as exc:
        logger.warning(
            "⚠️ DB busy checking status for %s %s: %s",
            symbol, timeframe, exc,
        )
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": 0,
            "latest_candle": None,
            "last_open_time": "",
            "ready": False,
            "error": "Database temporarily busy",
        }


# =====================================================================
# 5. Positions Sync — النسخة النهائية
# =====================================================================

@router.post("/positions/sync")
async def sync_positions(
    req: schemas.PositionsSyncRequest,
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    مزامنة الصفقات المفتوحة.

    ✅ إصلاحات:
    - إزالة TRUNCATE.
    - حفظ current_price الحقيقي من EA.
    - حفظ identifier, magic, open_time.
    - حذف الصفقات المغلقة لنفس الحساب فقط عبر NOT IN مع expanding bindparam.
    - تنظيف حالات الإدارة للصفقات المغلقة.
    """
    _authorize(x_mt5_key)

    account = req.account_number
    if not account or account <= 0:
        raise HTTPException(400, "account_number مطلوب")

    try:
        # --------------------------------------------------------
        # 1. UPSERT لكل صفقة
        # --------------------------------------------------------
        for pos in req.positions:
            current_p = float(pos.current_price or 0.0)
            if current_p <= 0:
                current_p = float(pos.price_open or 0.0)

            open_time = pos.open_time or pos.updated_at or None

            await db.execute(text("""
                INSERT INTO open_positions (
                    ticket, account_number, identifier, magic,
                    symbol, position_type, volume,
                    open_price, current_price, sl, tp, profit,
                    open_time, updated_at
                )
                VALUES (
                    :ticket, :account_number, :identifier, :magic,
                    :sym, :type, :vol,
                    :open_p, :curr_p, :sl, :tp, :profit,
                    :open_time, NOW()
                )
                ON CONFLICT (ticket) DO UPDATE SET
                    account_number = EXCLUDED.account_number,
                    identifier = EXCLUDED.identifier,
                    magic = EXCLUDED.magic,
                    symbol = EXCLUDED.symbol,
                    position_type = EXCLUDED.position_type,
                    volume = EXCLUDED.volume,
                    open_price = EXCLUDED.open_price,
                    current_price = EXCLUDED.current_price,
                    sl = EXCLUDED.sl,
                    tp = EXCLUDED.tp,
                    profit = EXCLUDED.profit,
                    open_time = COALESCE(
                        open_positions.open_time,
                        EXCLUDED.open_time
                    ),
                    updated_at = NOW()
            """), {
                "ticket": int(pos.ticket),
                "account_number": account,
                "identifier": int(pos.identifier) if pos.identifier else None,
                "magic": int(pos.magic) if pos.magic else None,
                "sym": pos.symbol,
                "type": pos.side,
                "vol": pos.volume,
                "open_p": pos.price_open,
                "curr_p": current_p,
                "sl": pos.stop_loss,
                "tp": pos.take_profit,
                "profit": pos.profit,
                "open_time": open_time,
            })

        # --------------------------------------------------------
        # 2. حذف الصفقات المغلقة لنفس الحساب فقط
        # ✅ الطريقة الصحيحة: NOT IN مع expanding bindparam
        # --------------------------------------------------------
        if req.positions:
            live_tickets = [int(p.ticket) for p in req.positions if p.ticket]

            if live_tickets:
                from sqlalchemy import bindparam

                stmt = text("""
                    DELETE FROM open_positions
                    WHERE account_number = :acc
                      AND ticket NOT IN :tickets
                """).bindparams(
                    bindparam("tickets", expanding=True)
                )

                await db.execute(stmt, {
                    "acc": account,
                    "tickets": live_tickets,
                })
            else:
                # لا تذاكر صالحة — احذف كل صفوف الحساب
                await db.execute(text("""
                    DELETE FROM open_positions
                    WHERE account_number = :acc
                """), {"acc": account})
        else:
            # لا صفقات — احذف كل صفوف الحساب
            await db.execute(text("""
                DELETE FROM open_positions
                WHERE account_number = :acc
            """), {"acc": account})

        await db.commit()

        # --------------------------------------------------------
        # 3. تنظيف حالات الإدارة للصفقات المغلقة
        # --------------------------------------------------------
        try:
            command_repo = PositionCommandRepository(db)
            open_tickets = {int(p.ticket) for p in req.positions if p.ticket}
            await command_repo.cleanup_states_for_closed_positions(
                account_number=account,
                open_tickets=open_tickets,
            )
        except Exception as cleanup_exc:
            logger.warning("State cleanup failed: %s", cleanup_exc)

        return {"status": "success", "count": len(req.positions)}

    except Exception as exc:
        await db.rollback()
        logger.exception("Sync positions failed: %s", exc)
        raise HTTPException(500, "Sync positions failed")
# =====================================================================
# 6. Pending Orders Sync
# =====================================================================

@router.post("/pending-orders/sync")
async def sync_pending_orders(
    req: schemas.PendingOrdersSyncRequest,
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    مزامنة الأوامر المعلقة.

    ✅ إصلاح: استخدام NOT IN مع expanding bindparam بدل != ALL.
    """
    _authorize(x_mt5_key)

    account = req.account_number
    if not account or account <= 0:
        raise HTTPException(400, "account_number مطلوب")

    try:
        # 1. UPSERT
        for o in req.orders:
            await db.execute(text("""
                INSERT INTO pending_orders (
                    ticket, account_number, symbol, side, volume,
                    price_open, stop_loss, take_profit, updated_at
                )
                VALUES (
                    :ticket, :account_number, :sym, :side, :vol,
                    :price_open, :sl, :tp, NOW()
                )
                ON CONFLICT (ticket) DO UPDATE SET
                    account_number = EXCLUDED.account_number,
                    symbol = EXCLUDED.symbol,
                    side = EXCLUDED.side,
                    volume = EXCLUDED.volume,
                    price_open = EXCLUDED.price_open,
                    stop_loss = EXCLUDED.stop_loss,
                    take_profit = EXCLUDED.take_profit,
                    updated_at = NOW()
            """), {
                "ticket": int(o.ticket),
                "account_number": account,
                "sym": o.symbol,
                "side": o.side,
                "vol": o.volume,
                "price_open": o.price_open,
                "sl": o.stop_loss,
                "tp": o.take_profit,
            })

        # 2. حذف المفقود
        # ✅ الطريقة الصحيحة: NOT IN مع expanding bindparam
        if req.orders:
            live_tickets = [int(o.ticket) for o in req.orders if o.ticket]

            if live_tickets:
                from sqlalchemy import bindparam

                stmt = text("""
                    DELETE FROM pending_orders
                    WHERE account_number = :acc
                      AND ticket NOT IN :tickets
                """).bindparams(
                    bindparam("tickets", expanding=True)
                )

                await db.execute(stmt, {
                    "acc": account,
                    "tickets": live_tickets,
                })
            else:
                await db.execute(text("""
                    DELETE FROM pending_orders
                    WHERE account_number = :acc
                """), {"acc": account})
        else:
            await db.execute(text("""
                DELETE FROM pending_orders
                WHERE account_number = :acc
            """), {"acc": account})

        await db.commit()
        return {"status": "success", "count": len(req.orders)}

    except Exception as exc:
        await db.rollback()
        logger.exception("Pending orders sync failed: %s", exc)
        raise HTTPException(500, "Pending orders synchronization failed")

# =====================================================================
# 7. Symbol Specs Sync
# =====================================================================

@router.post("/specs/sync")
async def sync_symbol_specs(
    request: Request,
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    مزامنة مواصفات الرموز.
    """
    _authorize(x_mt5_key)

    try:
        try:
            raw_json = await request.json()
        except Exception:
            raw_json = request._json if hasattr(request, "_json") else {}

        specs_data = raw_json if isinstance(raw_json, list) else [raw_json]

        count = 0
        for s in specs_data:
            if not isinstance(s, dict):
                continue
            symbol = str(s.get("symbol", "")).strip()
            if not symbol:
                continue

            point = float(s.get("point", 0.00001))
            digits = int(s.get("digits", 5))

            tick_value = float(s.get("tick_value", 1.0))
            tick_size = float(s.get("tick_size", 0.00001))
            contract_size = float(s.get("contract_size", 100000.0))

            volume_min = float(s.get("volume_min") or s.get("min_lot") or 0.01)
            volume_max = float(s.get("volume_max") or s.get("max_lot") or 100.0)
            volume_step = float(s.get("volume_step") or s.get("lot_step") or 0.01)

            stops_level_points = int(
                s.get("stops_level_points") or s.get("stops") or 0
            )
            freeze_level_points = int(
                s.get("freeze_level_points") or s.get("freeze") or 0
            )

            await db.execute(text("""
                INSERT INTO symbol_specs (
                    symbol, digits, point, tick_size, tick_value,
                    volume_min, volume_max, volume_step,
                    stops_level_points, freeze_level_points,
                    contract_size, updated_at
                )
                VALUES (
                    :sym, :digits, :point, :ts, :tv,
                    :vmin, :vmax, :vstep,
                    :stops, :freeze,
                    :cs, NOW()
                )
                ON CONFLICT (symbol) DO UPDATE SET
                    digits = EXCLUDED.digits,
                    point = EXCLUDED.point,
                    tick_size = EXCLUDED.tick_size,
                    tick_value = EXCLUDED.tick_value,
                    volume_min = EXCLUDED.volume_min,
                    volume_max = EXCLUDED.volume_max,
                    volume_step = EXCLUDED.volume_step,
                    stops_level_points = EXCLUDED.stops_level_points,
                    freeze_level_points = EXCLUDED.freeze_level_points,
                    contract_size = EXCLUDED.contract_size,
                    updated_at = NOW()
            """), {
                "sym": symbol,
                "digits": digits,
                "point": point,
                "ts": tick_size,
                "tv": tick_value,
                "vmin": volume_min,
                "vmax": volume_max,
                "vstep": volume_step,
                "stops": stops_level_points,
                "freeze": freeze_level_points,
                "cs": contract_size,
            })
            count += 1

        await db.commit()
        return {"status": "success", "count": count}

    except Exception as exc:
        await db.rollback()
        logger.exception("Specs sync failed: %s", exc)
        raise HTTPException(500, "Specs synchronization failed")


# =====================================================================
# 8. Commands Polling
# =====================================================================

@router.get("/commands")
async def get_pending_commands(
    limit: int = 10,
    ea_id: Optional[str] = None,
    account_number: Optional[int] = Query(default=None),
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    جلب أوامر فتح صفقات جديدة.
    """
    _authorize(x_mt5_key)

    if not account_number or account_number <= 0:
        raise HTTPException(400, "account_number مطلوب")

    try:
        repo = TradeRepository(db)
        commands = await repo.get_pending_commands(
            account_number=account_number,
            ea_id=ea_id or "",
            limit=limit,
        )

        result = []
        for c in commands:
            created_epoch = None
            if c.created_at:
                try:
                    created_epoch = c.created_at.timestamp()
                except Exception:
                    created_epoch = None

            result.append({
                "id": str(c.id),
                "command_id": str(c.id),
                "account_number": c.account_number or 0,
                "ea_id": c.ea_id or "",
                "symbol": c.symbol,
                "order_type": c.order_type,
                "side": c.order_type,
                "volume": float(c.lot_size),
                "entry_price": float(c.entry_price or 0.0),
                "sl": float(c.stop_loss or 0.0),
                "tp": float(c.take_profit or 0.0),
                "status": c.status,
                "strategy_name": c.strategy_name or "",
                "signal_key": c.signal_key or "",
                "created_at": c.created_at.isoformat() if c.created_at else "",
                "created_epoch": created_epoch or 0,
                "expires_epoch": 0,
            })
        return result

    except Exception as exc:
        logger.exception("Get pending commands failed: %s", exc)
        raise HTTPException(500, "Failed to get commands")


# =====================================================================
# 9. Command ACK
# =====================================================================

@router.post("/commands/{command_id}/ack")
async def acknowledge_command(
    command_id: str,
    payload: CommandAck,
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    تأكيد استلام أمر فتح صفقة.
    """
    _authorize(x_mt5_key)

    try:
        row = (await db.execute(text("""
            UPDATE trade_commands
            SET status = 'processing', updated_at = NOW()
            WHERE id = CAST(:cmd_id AS UUID)
              AND status = 'pending'
            RETURNING id
        """), {"cmd_id": command_id})).first()

        await db.commit()

        if not row:
            raise HTTPException(
                404,
                "Command not found or already processed",
            )

        return {"status": "success", "command_id": command_id}

    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("Ack failed: %s", exc)
        raise HTTPException(500, "Ack failed")


# =====================================================================
# 10. Command Report
# =====================================================================

@router.post("/commands/{command_id}/report")
async def report_execution_single(
    command_id: str,
    report: CommandReport,
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    تقرير تنفيذ أمر فتح صفقة.
    """
    _authorize(x_mt5_key)

    try:
        repo = TradeRepository(db)
        updated = await repo.update_command_result(
            command_id=command_id,
            status=report.status,
            mt5_ticket=report.mt5_ticket or None,
            mt5_order_ticket=report.mt5_order_ticket or None,
            mt5_deal_ticket=report.mt5_deal_ticket or None,
            fill_price=report.fill_price or None,
            executed_volume=report.executed_volume or None,
            mt5_retcode=report.mt5_retcode or None,
            error_message=report.error_message or None,
        )

        if updated is None:
            raise HTTPException(404, "Command not found")

        return {"status": "success", "command_id": command_id}

    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("Report execution failed: %s", exc)
        raise HTTPException(500, "Report execution failed")


# =====================================================================
# 11. Batch Reports
# =====================================================================

@router.post("/reports")
async def report_execution(
    reports: List[schemas.CommandReportRequest],
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    _authorize(x_mt5_key)
    try:
        repo = TradeRepository(db)
        for rep in reports:
            cmd_id = getattr(rep, "command_id", None)
            if not cmd_id:
                continue
            await repo.update_command_result(
                command_id=str(cmd_id),
                status=rep.status,
                mt5_ticket=rep.mt5_ticket,
                mt5_order_ticket=rep.mt5_order_ticket,
                mt5_deal_ticket=rep.mt5_deal_ticket,
                fill_price=rep.fill_price,
                error_message=rep.error_message or "",
            )
        return {"status": "success", "count": len(reports)}

    except Exception as exc:
        await db.rollback()
        logger.exception("Batch report failed: %s", exc)
        raise HTTPException(500, "Report execution failed")


# =====================================================================
# 12. Position Management Commands
# =====================================================================

@router.get("/position-commands")
async def get_pending_position_commands(
    limit: int = 10,
    ea_id: Optional[str] = None,
    account_number: Optional[int] = Query(default=None),
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    جلب أوامر إدارة الصفقات المعلقة.
    """
    _authorize(x_mt5_key)

    if not account_number or account_number <= 0:
        raise HTTPException(400, "account_number مطلوب")

    try:
        repo = PositionCommandRepository(db)
        commands = await repo.get_pending_commands(
            account_number=account_number,
            ea_id=ea_id or "",
            limit=limit,
        )

        result = []
        for c in commands:
            created_epoch = None
            if c.created_at:
                try:
                    created_epoch = c.created_at.timestamp()
                except Exception:
                    created_epoch = None

            expires_epoch = None
            if c.expires_at:
                try:
                    expires_epoch = c.expires_at.timestamp()
                except Exception:
                    expires_epoch = None

            result.append({
                "id": str(c.id),
                "command_id": str(c.id),
                "account_number": c.account_number,
                "ea_id": c.ea_id or "",
                "position_ticket": c.position_ticket,
                "position_identifier": c.position_identifier,
                "symbol": c.symbol,
                "action": c.action,
                "new_sl": float(c.new_sl) if c.new_sl is not None else None,
                "new_tp": float(c.new_tp) if c.new_tp is not None else None,
                "close_volume": float(c.close_volume) if c.close_volume is not None else None,
                "reason": c.reason or "",
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else "",
                "created_epoch": created_epoch,
                "expires_at": c.expires_at.isoformat() if c.expires_at else None,
                "expires_epoch": expires_epoch,
            })
        return result

    except Exception as exc:
        logger.exception("Get position commands failed: %s", exc)
        raise HTTPException(500, "Failed to get position commands")


@router.post("/position-commands/{command_id}/ack")
async def acknowledge_position_command(
    command_id: str,
    payload: PositionCommandAck,
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    تأكيد استلام أمر إدارة صفقة.
    """
    _authorize(x_mt5_key)

    try:
        repo = PositionCommandRepository(db)
        cmd = await repo.claim_command(command_id)

        if cmd is None:
            raise HTTPException(
                404,
                "Position command not found or already claimed",
            )

        return {"status": "success", "command_id": command_id}

    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("Position command ack failed: %s", exc)
        raise HTTPException(500, "Position command ack failed")


@router.post("/position-commands/{command_id}/report")
async def report_position_command(
    command_id: str,
    report: PositionCommandReport,
    x_mt5_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    تقرير تنفيذ أمر إدارة صفقة.
    """
    _authorize(x_mt5_key)

    try:
        repo = PositionCommandRepository(db)
        updated = await repo.update_command_result(
            command_id=command_id,
            status=report.status,
            mt5_retcode=report.mt5_retcode,
            error_message=report.error_message,
            executed_sl=report.executed_sl,
            executed_tp=report.executed_tp,
        )

        if updated is None:
            raise HTTPException(404, "Position command not found")

        return {"status": "success", "command_id": command_id}

    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.exception("Position command report failed: %s", exc)
        raise HTTPException(500, "Position command report failed")
