import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Header, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy import text
from database import SessionLocal
from app.config import config

# استيراد محرك التداول (العقل المدبر) لتشغيله في الخلفية
# (تأكد من تعديل المسار 'app.YOUR_PATH' للمكان الفعلي لملف strategy_executor)
from app.services.strategy_evaluator import evaluate_and_execute_strategy
router = APIRouter(prefix="/api/v1/mt5", tags=["MT5 EA Integration"])
logger = logging.getLogger("AlqasemyTrader.MT5")

# ===================================================================
# Pydantic Models (متوافقة بالكامل مع EA v14.0)
# ===================================================================

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
    symbol: str
    timeframe: str
    candles: List[CandleItem] = Field(default_factory=list)
    ea_id: Optional[str] = None

class PositionItem(BaseModel):
    ticket: int
    symbol: str
    side: str
    volume: float = Field(gt=0)
    price_open: float = Field(gt=0)
    stop_loss: float = Field(ge=0)
    take_profit: float = Field(ge=0)
    profit: float
    updated_at: Optional[str] = None

class PositionsSyncRequest(BaseModel):
    account_number: int
    ea_id: str = ""
    magic: Optional[int] = None
    positions: List[PositionItem] = Field(default_factory=list)

class PendingOrderItem(BaseModel):
    ticket: int
    symbol: str
    side: str
    volume: float = Field(gt=0)
    price_open: float = Field(gt=0)
    stop_loss: float = Field(ge=0)
    take_profit: float = Field(ge=0)
    updated_at: Optional[str] = None

class PendingOrdersSyncRequest(BaseModel):
    account_number: int
    ea_id: str = ""
    magic: Optional[int] = None
    orders: List[PendingOrderItem] = Field(default_factory=list)

class AccountHeartbeat(BaseModel):
    account_number: int
    balance: float
    equity: float
    margin: float
    free_margin: float
    profit: float
    is_connected: bool
    margin_level: float | None = None
    server: Optional[str] = None
    currency: Optional[str] = None
    leverage: Optional[int] = None
    is_trade_allowed: Optional[bool] = None
    ea_id: Optional[str] = None
    ea_version: Optional[str] = None

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

class CommandAckRequest(BaseModel):
    ea_id: str = ""

# ===================================================================
# Core Validation & Auth
# ===================================================================

def _authorize(x_mt5_key: str | None):
    # [مؤقت] إيقاف الحماية للتحقق من الاتصال
    pass

_ALLOWED_TIMEFRAMES = {
    "M1", "M2", "M3", "M4", "M5", "M6", "M10", "M12", "M15", "M20", "M30",
    "H1", "H2", "H3", "H4", "H6", "H8", "H12",
    "D1", "W1", "MN1"
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
            SELECT id FROM candles
            WHERE symbol_name=:symbol AND timeframe=:tf
            ORDER BY open_time DESC
            OFFSET :retention
        )
    """), {"symbol": symbol, "tf": timeframe, "retention": retention})


# ===================================================================
# Background Tasks (المحرك الداخلي)
# ===================================================================

def run_strategy_in_background(symbol: str, timeframe: str, latest_candle: CandleItem, ea_id: str):
    """
    هذه الدالة تعمل في الخلفية فور استلام شموع جديدة،
    تقوم بجمع البيانات وتمريرها لمحرك التداول (العقل).
    """
    db = SessionLocal()
    try:
        # البحث عن رقم الحساب (UUID) المرتبط بهذا الإكسبرت
        account = db.execute(
            text("SELECT id FROM trading_accounts WHERE ea_id=:ea_id LIMIT 1"), 
            {"ea_id": ea_id}
        ).mappings().first()
        
        if not account:
            logger.warning(f"No account linked to EA {ea_id}. Strategy execution skipped.")
            return
            
        account_id = str(account["id"])

        # تجهيز بيانات السوق كما يطلبها ملف الاستراتيجية
        market_data = {
            "symbol": symbol,
            "timeframe": timeframe,
            "open_time": latest_candle.open_time,
            "open": latest_candle.open,
            "high": latest_candle.high,
            "low": latest_candle.low,
            "close": latest_candle.close,
            "volume": latest_candle.volume,
            "ea_id": ea_id,
            "candle_key": latest_candle.open_time
        }

        # إيقاظ العقل المدبر واستدعاء دالة التقييم والتنفيذ
        # يمكنك تغيير "scalping" هنا لتلائم الاستراتيجية المطلوبة
        evaluate_and_execute_strategy(
            db=db, 
            account_id=account_id, 
            strategy_name="scalping", 
            market_data=market_data
        )
        
    except Exception as e:
        logger.error(f"Background Strategy Execution failed: {e}")
    finally:
        db.close()


# ===================================================================
# Endpoints
# ===================================================================

@router.post("/candles/sync")
async def sync_candles(
    request: CandlesSyncRequest, 
    background_tasks: BackgroundTasks, # تمت الإضافة هنا للمهام الخلفية
    x_mt5_key: str | None = Header(default=None)
):
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

        for symbol, tf in touched:
            _prune_candles(db, symbol, tf)

        db.commit()

        # =========================================================
        # السحر هنا: تشغيل الاستراتيجية في الخلفية فور استلام الشموع
        # =========================================================
        if request.ea_id and len(request.candles) > 0:
            latest_candle = request.candles[-1] # نأخذ أحدث شمعة
            background_tasks.add_task(
                run_strategy_in_background,
                symbol=request.symbol.upper(),
                timeframe=request.timeframe.upper(),
                latest_candle=latest_candle,
                ea_id=request.ea_id
            )
        # =========================================================

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
        rows = db.execute(text("""
            SELECT id,symbol,order_type,lot_size,entry_price,stop_loss,take_profit,
                   status,created_at,strategy_name,signal_key,ea_id,EXTRACT(EPOCH FROM created_at) AS created_epoch
            FROM trade_commands
            WHERE status='pending'
              AND (CAST(:ea_id AS TEXT) IS NULL OR ea_id='' OR ea_id=CAST(:ea_id AS TEXT))
            ORDER BY created_at ASC
            LIMIT :limit
        """), {"ea_id": ea_id, "limit": min(max(limit, 1), 20)}).mappings().all()
        
        return [dict(r, id=str(r["id"]), command_id=str(r["id"]), order_type=r["order_type"].upper(),
                     side=r["order_type"].upper(), volume=float(r["lot_size"]), sl=float(r["stop_loss"]),
                     tp=float(r["take_profit"])) for r in rows]
    finally:
        db.close()


@router.post("/commands/{command_id}/ack")
async def ack_command(command_id: str, ack_req: CommandAckRequest, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        result = db.execute(text("""
            UPDATE trade_commands SET status='processing', ea_id=COALESCE(NULLIF(:ea_id,''),ea_id), updated_at=NOW()
            WHERE id=:id AND status='pending'
            RETURNING id
        """), {"id": command_id, "ea_id": ack_req.ea_id or ""}).first()
        
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
    
    allowed = {"executed", "partial", "placed", "failed", "cancelled", "expired", "ignored"}
    if status_val not in allowed:
        raise HTTPException(400, f"Invalid command final status: {status_val}")
        
    order_ticket = data.get("mt5_order_ticket", 0)
    deal_ticket = data.get("mt5_deal_ticket", 0)
    fill_price = data.get("fill_price", 0.0)
    error_msg = str(data.get("error_message", data.get("message", "")))[:500]

    db = SessionLocal()
    try:
        # 🛠️ التعديل الاحترافي هنا: السماح بتحديث الأمر سواء كان pending أو processing لمنع أخطاء التضارب
        result = db.execute(text("""
            UPDATE trade_commands 
            SET status=:status, 
                error_message=:error,
                mt5_order_ticket=:order_ticket,
                mt5_deal_ticket=:deal_ticket,
                fill_price=:fill_price,
                mt5_ticket=COALESCE(mt5_ticket, NULLIF(:order_ticket, 0)),
                updated_at=NOW()
            WHERE id=:id AND status IN ('pending', 'processing')
            RETURNING id
        """), {
            "id": command_id, 
            "status": status_val, 
            "error": error_msg,
            "order_ticket": order_ticket,
            "deal_ticket": deal_ticket,
            "fill_price": fill_price
        }).first()
        
        if not result:
            raise HTTPException(409, "Command is not in a valid state for reporting")
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
    if spec.point <= 0 or spec.tick_size <= 0 or spec.volume_min <= 0 or spec.volume_step <= 0:
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
async def sync_account(account_data: AccountHeartbeat, x_mt5_key: str | None = Header(default=None)):
    _authorize(x_mt5_key)
    db = SessionLocal()
    try:
        margin_level = account_data.margin_level if account_data.margin_level is not None else (account_data.equity / account_data.margin * 100 if account_data.margin > 0 else 0)
        server_name = account_data.server or "unknown"

        result = db.execute(text("""
            UPDATE trading_accounts SET balance=:balance,equity=:equity,margin=:margin,free_margin=:free_margin,
              profit=:profit,margin_level=:margin_level,is_connected=:connected,last_sync=NOW(),last_heartbeat=NOW()
            WHERE account_number=:account AND server=:server
        """), {
            "balance": account_data.balance, "equity": account_data.equity, "margin": account_data.margin,
            "free_margin": account_data.free_margin, "profit": account_data.profit, "margin_level": margin_level,
            "connected": account_data.is_connected, "account": account_data.account_number, "server": server_name
        })
                
        if result.rowcount == 0:
            db.execute(text("""
                INSERT INTO trading_accounts(account_number,server,balance,equity,margin,free_margin,profit,margin_level,is_connected,last_sync,last_heartbeat)
                VALUES(:account,:server,:balance,:equity,:margin,:free_margin,:profit,:margin_level,:connected,NOW(),NOW())
                ON CONFLICT(account_number, server) DO NOTHING
            """), {
                "account": account_data.account_number, "server": server_name, "balance": account_data.balance, 
                "equity": account_data.equity, "margin": account_data.margin, "free_margin": account_data.free_margin, 
                "profit": account_data.profit, "margin_level": margin_level, "connected": account_data.is_connected
            })
            
        db.commit()
        return {"status": "success", "account_number": account_data.account_number}
        
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
