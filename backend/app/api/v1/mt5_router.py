import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel, Field
from typing import List
from sqlalchemy import text
from database import SessionLocal
from app.config import config

router = APIRouter(prefix="/api/v1/mt5", tags=["MT5 EA Integration"])
logger = logging.getLogger("AlqasemyTrader.MT5")


class CandleItem(BaseModel):
    symbol: str
    timeframe: str
    open_time: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class CandlesSyncRequest(BaseModel):
    candles: List[CandleItem]
    source: str
    ea_id: str


class PositionItem(BaseModel):
    ticket: str
    symbol: str
    side: str
    volume: float = Field(gt=0)
    price_open: float = Field(gt=0)
    stop_loss: float = 0.0
    take_profit: float = 0.0
    profit: float = 0.0


class PositionsSyncRequest(BaseModel):
    account_number: int
    ea_id: str
    positions: List[PositionItem] = []


class PendingOrderItem(BaseModel):
    ticket: str
    symbol: str
    side: str
    volume: float = Field(gt=0)
    price_open: float = Field(gt=0)
    stop_loss: float = 0.0
    take_profit: float = 0.0


class PendingOrdersSyncRequest(BaseModel):
    account_number: int
    ea_id: str
    orders: List[PendingOrderItem] = []


class AccountHeartbeat(BaseModel):
    account_number: int
    balance: float
    equity: float
    margin: float
    free_margin: float
    profit: float
    is_connected: bool
    margin_level: float | None = None


class SymbolSpecSync(BaseModel):
    symbol: str
    digits: int
    point: float
    tick_size: float
    tick_value: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level_points: int = 0
    contract_size: float = 0.0


def _authorize(x_mt5_key: str | None):
    if config.require_mt5_api_key:
        if not config.mt5_api_key:
            raise HTTPException(503, "MT5 API is locked: MT5_API_KEY is not configured")
        if x_mt5_key != config.mt5_api_key:
            raise HTTPException(401, "Invalid MT5 API key")


_ALLOWED_TIMEFRAMES = {
    config.direction_timeframe,
    config.confirmation_timeframe,
    config.entry_timeframe,
}
_ALLOWED_SYMBOLS = set(config.symbols)


def _validate_candle(c: CandleItem) -> tuple[str, str]:
    symbol = c.symbol.upper().strip()
    timeframe = c.timeframe.upper().strip()
    if symbol not in _ALLOWED_SYMBOLS:
        raise HTTPException(400, f"Unsupported symbol: {symbol}")
    if timeframe not in _ALLOWED_TIMEFRAMES:
        raise HTTPException(400, f"Unsupported timeframe: {timeframe}")
    if c.open <= 0 or c.high <= 0 or c.low <= 0 or c.close <= 0:
        raise HTTPException(400, "Candle prices must be positive")
    if c.high < max(c.open, c.close) or c.low > min(c.open, c.close):
        raise HTTPException(400, "Invalid OHLC geometry")
    if c.volume < 0:
        raise HTTPException(400, "Candle volume cannot be negative")
    try:
        parsed = datetime.fromisoformat(c.open_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "Invalid candle open_time") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.replace(tzinfo=None)
    # MQL5 sends broker-server wall-clock time without an offset. The backend
    # preserves that value as the canonical candle identity; it does not try
    # to compare it to the backend server's timezone.
    return symbol, timeframe


def _retention_for(timeframe: str) -> int:
    if timeframe == config.direction_timeframe:
        return config.direction_candle_retention
    if timeframe == config.confirmation_timeframe:
        return config.confirmation_candle_retention
    return config.entry_candle_retention


def _prune_candles(db, symbol: str, timeframe: str) -> None:
    retention = max(1, _retention_for(timeframe))
    db.execute(text("""
        DELETE FROM candles
        WHERE id IN (
            SELECT id
            FROM candles
            WHERE symbol_name=:symbol AND timeframe=:tf
            ORDER BY open_time DESC
            OFFSET :retention
        )
    """), {"symbol": symbol, "tf": timeframe, "retention": retention})


@router.post("/candles/sync")
async def sync_candles(request: CandlesSyncRequest, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    if not request.candles:
        return {"status": "success", "inserted": 0, "received": 0}

    db = SessionLocal()
    try:
        touched: set[tuple[str, str]] = set()
        inserted = 0
        for c in request.candles:
            symbol, tf = _validate_candle(c)
            result = db.execute(text("""
                INSERT INTO candles (symbol_name,timeframe,open_time,open,high,low,close,volume)
                VALUES (:symbol,:tf,:ot,:open,:high,:low,:close,:volume)
                ON CONFLICT (symbol_name,timeframe,open_time) DO UPDATE SET
                  open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                  close=EXCLUDED.close, volume=EXCLUDED.volume
            """), {
                "symbol": symbol, "tf": tf, "ot": c.open_time,
                "open": c.open, "high": c.high, "low": c.low,
                "close": c.close, "volume": c.volume,
            })
            inserted += int(result.rowcount or 0)
            touched.add((symbol, tf))

        # Keep a bounded history while preserving enough data for MTF recovery.
        for symbol, tf in touched:
            _prune_candles(db, symbol, tf)

        db.commit()
        return {
            "status": "success",
            "inserted": inserted,
            "received": len(request.candles),
            "retention": {tf: _retention_for(tf) for _, tf in touched},
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Candle sync failed: %s", exc)
        raise HTTPException(500, "Candle synchronization failed")
    finally:
        db.close()


@router.get("/candles/status")
async def candle_sync_status(symbol: str, timeframe: str, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    symbol = symbol.upper().strip()
    timeframe = timeframe.upper().strip()
    if symbol not in _ALLOWED_SYMBOLS:
        raise HTTPException(400, f"Unsupported symbol: {symbol}")
    if timeframe not in _ALLOWED_TIMEFRAMES:
        raise HTTPException(400, f"Unsupported timeframe: {timeframe}")

    db = SessionLocal()
    try:
        row = db.execute(text("""
            SELECT MAX(open_time) AS last_open_time, COUNT(*) AS candle_count
            FROM candles
            WHERE symbol_name=:symbol AND timeframe=:tf
        """), {"symbol": symbol, "tf": timeframe}).mappings().first()
        last_open_time = row["last_open_time"] if row else None
        count = int(row["candle_count"] or 0) if row else 0
        return {
            "status": "success",
            "symbol": symbol,
            "timeframe": timeframe,
            "last_open_time": last_open_time,
            "candle_count": count,
            "required_initial": (
                config.direction_candle_limit if timeframe == config.direction_timeframe
                else config.confirmation_candle_limit if timeframe == config.confirmation_timeframe
                else config.entry_candle_limit
            ),
        }
    finally:
        db.close()


@router.get("/commands")
async def get_pending_commands(ea_id: str | None = None, limit: int = 10, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        # The caller receives only unclaimed commands. Claim is atomic in /ack.
        rows = db.execute(text("""
            SELECT id,symbol,order_type,lot_size,entry_price,stop_loss,take_profit,
                   status,created_at,strategy_name,signal_key,ea_id,EXTRACT(EPOCH FROM created_at) AS created_epoch
            FROM trade_commands
            WHERE status='pending'
              AND (:ea_id IS NULL OR ea_id='' OR ea_id=:ea_id)
            ORDER BY created_at ASC
            LIMIT :limit
        """), {"ea_id": ea_id, "limit": min(max(limit, 1), 20)}).mappings().all()
        return [dict(r, id=str(r["id"]), command_id=str(r["id"]), order_type=r["order_type"].upper(),
                     side=r["order_type"].upper(), volume=float(r["lot_size"]), sl=float(r["stop_loss"]),
                     tp=float(r["take_profit"])) for r in rows]
    finally:
        db.close()


@router.post("/commands/{command_id}/ack")
async def ack_command(command_id: str, ea_id: str | None = None, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        result = db.execute(text("""
            UPDATE trade_commands SET status='processing', ea_id=COALESCE(NULLIF(:ea_id,''),ea_id), updated_at=NOW()
            WHERE id=:id AND status='pending'
            RETURNING id
        """), {"id": command_id, "ea_id": ea_id or ""}).first()
        if not result:
            db.rollback()
            raise HTTPException(409, "Command is already claimed or does not exist")
        db.commit()
        return {"status": "success", "command_id": command_id, "state": "processing"}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Ack failed: %s", exc)
        raise HTTPException(500, "Command acknowledgement failed")
    finally:
        db.close()


@router.post("/commands/{command_id}/report")
async def report_command(command_id: str, request: Request, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    data = await request.json()
    status_val = str(data.get("status", "failed")).lower()
    allowed = {"executed", "failed", "cancelled", "expired", "ignored"}
    if status_val not in allowed:
        raise HTTPException(400, "Invalid command final status")
    db = SessionLocal()
    try:
        result = db.execute(text("""
            UPDATE trade_commands SET status=:status, error_message=:error, updated_at=NOW()
            WHERE id=:id AND status='processing'
            RETURNING id
        """), {"id": command_id, "status": status_val, "error": str(data.get("message", data.get("error_message", "")))[:500]}).first()
        if not result:
            raise HTTPException(409, "Command is not in processing state")
        db.commit()
        return {"status": "success", "command_id": command_id, "state": status_val}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Report failed: %s", exc)
        raise HTTPException(500, "Command report failed")
    finally:
        db.close()


@router.post("/specs/sync")
async def sync_specs(spec: SymbolSpecSync, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    if spec.point <= 0 or spec.tick_size <= 0 or spec.tick_value <= 0 or spec.volume_min <= 0 or spec.volume_step <= 0:
        raise HTTPException(400, "Invalid symbol specification")
    db = SessionLocal()
    try:
        db.execute(text("""
            INSERT INTO symbol_specs(symbol,digits,point,tick_size,tick_value,volume_min,volume_max,volume_step,stops_level_points,contract_size,updated_at)
            VALUES(:symbol,:digits,:point,:tick_size,:tick_value,:vmin,:vmax,:vstep,:stops,:contract,NOW())
            ON CONFLICT(symbol) DO UPDATE SET digits=EXCLUDED.digits,point=EXCLUDED.point,tick_size=EXCLUDED.tick_size,
              tick_value=EXCLUDED.tick_value,volume_min=EXCLUDED.volume_min,volume_max=EXCLUDED.volume_max,
              volume_step=EXCLUDED.volume_step,stops_level_points=EXCLUDED.stops_level_points,
              contract_size=EXCLUDED.contract_size,updated_at=NOW()
        """), {"symbol": spec.symbol.upper(), "digits": spec.digits, "point": spec.point,
               "tick_size": spec.tick_size, "tick_value": spec.tick_value, "vmin": spec.volume_min,
               "vmax": spec.volume_max, "vstep": spec.volume_step, "stops": spec.stops_level_points,
               "contract": spec.contract_size})
        db.commit()
        return {"status": "success", "symbol": spec.symbol.upper()}
    except Exception as exc:
        db.rollback()
        logger.exception("Spec sync failed: %s", exc)
        raise HTTPException(500, "Specification synchronization failed")
    finally:
        db.close()


@router.post("/account/sync")
async def sync_account(request: Request, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    data = await request.json()
    account_data = data.get("account", {})
    login = account_data.get("login")
    if login is None:
        raise HTTPException(400, "account.login is required")
    balance = float(account_data.get("balance", 0))
    equity = float(account_data.get("equity", 0))
    margin = float(account_data.get("margin", 0))
    free_margin = float(account_data.get("free_margin", 0))
    profit = float(account_data.get("profit", equity - balance))
    margin_level = float(account_data.get("margin_level", (equity / margin * 100 if margin > 0 else 0)))
    db = SessionLocal()
    try:
        result = db.execute(text("""
            UPDATE trading_accounts SET balance=:balance,equity=:equity,margin=:margin,free_margin=:free_margin,
              profit=:profit,margin_level=:margin_level,is_connected=true,last_sync=NOW(),last_heartbeat=NOW()
            WHERE account_number=:account
        """), {"balance": balance, "equity": equity, "margin": margin, "free_margin": free_margin,
               "profit": profit, "margin_level": margin_level, "account": login})
        if result.rowcount == 0:
            db.execute(text("""
                INSERT INTO trading_accounts(account_number,balance,equity,margin,free_margin,profit,margin_level,is_connected,last_sync,last_heartbeat)
                VALUES(:account,:balance,:equity,:margin,:free_margin,:profit,:margin_level,true,NOW(),NOW())
            """), {"account": login, "balance": balance, "equity": equity, "margin": margin,
                   "free_margin": free_margin, "profit": profit, "margin_level": margin_level})
        db.commit()
        return {"status": "success", "account_number": login}
    except Exception as exc:
        db.rollback()
        logger.exception("Account sync failed: %s", exc)
        raise HTTPException(500, "Account synchronization failed")
    finally:
        db.close()


@router.post("/positions/sync")
async def sync_positions(payload: PositionsSyncRequest, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM live_positions WHERE account_number=:account"), {"account": payload.account_number})
        for p in payload.positions:
            side = p.side.upper()
            if side not in {"BUY", "SELL"}:
                raise HTTPException(400, "Invalid position side")
            db.execute(text("""
                INSERT INTO live_positions(ticket,account_number,symbol,side,volume,price_open,stop_loss,take_profit,profit,updated_at)
                VALUES(:ticket,:account,:symbol,:side,:volume,:price,:sl,:tp,:profit,NOW())
            """), {"ticket": p.ticket, "account": payload.account_number, "symbol": p.symbol.upper(),
                   "side": side, "volume": p.volume, "price": p.price_open, "sl": p.stop_loss,
                   "tp": p.take_profit, "profit": p.profit})
        db.execute(text("""
            INSERT INTO position_snapshots(account_number,last_sync) VALUES(:account,NOW())
            ON CONFLICT(account_number) DO UPDATE SET last_sync=NOW()
        """), {"account": payload.account_number})
        db.commit()
        return {"status": "success", "positions": len(payload.positions)}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Position sync failed: %s", exc)
        raise HTTPException(500, "Position synchronization failed")
    finally:
        db.close()


@router.post("/pending-orders/sync")
async def sync_pending_orders(payload: PendingOrdersSyncRequest, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        db.execute(text("DELETE FROM pending_orders WHERE account_number=:account"), {"account": payload.account_number})
        for o in payload.orders:
            side = o.side.upper()
            if side not in {"BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}:
                raise HTTPException(400, "Invalid pending order type")
            db.execute(text("""
                INSERT INTO pending_orders(ticket,account_number,symbol,side,volume,price_open,stop_loss,take_profit,updated_at)
                VALUES(:ticket,:account,:symbol,:side,:volume,:price,:sl,:tp,NOW())
            """), {"ticket": o.ticket, "account": payload.account_number, "symbol": o.symbol.upper(),
                   "side": side, "volume": o.volume, "price": o.price_open, "sl": o.stop_loss, "tp": o.take_profit})
        db.commit()
        return {"status": "success", "orders": len(payload.orders)}
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Pending order sync failed: %s", exc)
        raise HTTPException(500, "Pending order synchronization failed")
    finally:
        db.close()


@router.post("/heartbeat")
async def account_heartbeat(account_data: AccountHeartbeat, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        margin_level = account_data.margin_level if account_data.margin_level is not None else (account_data.equity / account_data.margin * 100 if account_data.margin > 0 else 0)
        db.execute(text("""
            UPDATE trading_accounts SET balance=:balance,equity=:equity,margin=:margin,free_margin=:free_margin,
              profit=:profit,margin_level=:margin_level,is_connected=:connected,last_heartbeat=NOW(),last_sync=NOW()
            WHERE account_number=:account
        """), {"balance": account_data.balance, "equity": account_data.equity, "margin": account_data.margin,
               "free_margin": account_data.free_margin, "profit": account_data.profit, "margin_level": margin_level,
               "connected": account_data.is_connected, "account": account_data.account_number})
        db.commit()
        return {"status": "success", "account_number": account_data.account_number}
    finally:
        db.close()
