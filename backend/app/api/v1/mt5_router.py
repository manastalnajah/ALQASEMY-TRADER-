import time
import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import List
from datetime import datetime
from sqlalchemy import text

# الاستيراد الصحيح المطابق لملف قاعدة بياناتك
from database import SessionLocal

router = APIRouter(
    prefix="/api/v1/mt5",
    tags=["MT5 EA Integration"]
)
logger = logging.getLogger(__name__)

# ==========================================
# 1. مسار مزامنة الشموع والأسعار (Candles/Specs Sync) - مع تحسين السرعة الفائقة
# ==========================================
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

@router.post("/candles/sync")
async def sync_candles(request: CandlesSyncRequest):
    start_time = time.time()

    if not request.candles:
        return {"status": "success", "message": "No candles provided", "inserted": 0}

    logger.info(f"📥 Received {len(request.candles)} candles for EA: {request.ea_id}")

    values = []
    latest_candles = {}

    for c in request.candles:
        values.append({
            "symbol_name": c.symbol,
            "timeframe": c.timeframe,
            "open_time": c.open_time,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume
        })
        # الاحتفاظ بآخر شمعة لكل رمز لإنعاش أسعار السوق الحية
        latest_candles[c.symbol] = c

    # استعلام الإدخال الجماعي للشموع (Bulk Insert)
    insert_candles_query = text("""
        INSERT INTO candles 
        (symbol_name, timeframe, open_time, open, high, low, close, volume)
        VALUES (:symbol_name, :timeframe, :open_time, :open, :high, :low, :close, :volume)
        ON CONFLICT (symbol_name, timeframe, open_time) 
        DO UPDATE SET 
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume;
    """)

    db = SessionLocal()

    try:
        # 🚀 1. تنفيذ الإدخال الجماعي لكل الشموع دفعة واحدة بطلب واحد صاروخي
        db.execute(insert_candles_query, values)

        # 2. حفظ أسعار السوق الحية في جدول market_data
        for symbol, c in latest_candles.items():
            change = c.close - c.open
            change_percent = (change / c.open * 100) if c.open > 0 else 0.0

            update_market_query = text("""
                UPDATE market_data 
                SET bid = :bid, ask = :ask, high = :high, low = :low, 
                    volume = :volume, change = :change, change_percent = :change_percent, 
                    last_updated = :last_updated
                WHERE symbol = :symbol
            """)
            result = db.execute(update_market_query, {
                "bid": c.close, "ask": c.close, "high": c.high, "low": c.low,
                "volume": c.volume, "change": change, "change_percent": change_percent,
                "last_updated": datetime.utcnow().isoformat(), "symbol": symbol
            })

            if result.rowcount == 0:
                insert_market_query = text("""
                    INSERT INTO market_data 
                    (symbol, bid, ask, high, low, volume, change, change_percent, is_enabled, is_tradeable, last_updated)
                    VALUES 
                    (:symbol, :bid, :ask, :high, :low, :volume, :change, :change_percent, True, True, :last_updated)
                """)
                db.execute(insert_market_query, {
                    "symbol": symbol, "bid": c.close, "ask": c.close, "high": c.high, "low": c.low,
                    "volume": c.volume, "change": change, "change_percent": change_percent,
                    "last_updated": datetime.utcnow().isoformat()
                })

        db.commit()

        elapsed = time.time() - start_time
        logger.info(f"⚡ Successfully bulk-inserted/updated {len(request.candles)} candles in {elapsed:.4f} seconds")

        return {
            "status": "success", 
            "inserted": len(request.candles), 
            "time_seconds": round(elapsed, 4)
        }

    except Exception as e:
        db.rollback()
        error_msg = str(e) if str(e).strip() else repr(e)
        logger.error(f"❌ DATABASE ERROR in candles sync: {error_msg}")
        raise HTTPException(status_code=500, detail=f"Failed to sync candles: {error_msg}")

    finally:
        db.close()

@router.post("/specs/sync")
async def sync_specs(request: Request):
    return {"status": "success", "message": "Symbol specifications synced"}

# ==========================================
# 2. مسار الأوامر (Commands)
# ==========================================
@router.get("/commands")
async def get_pending_commands(ea_id: str = None, limit: int = 10):
    db = SessionLocal()
    try:
        query = text("""
            SELECT id, symbol, order_type, lot_size, stop_loss, take_profit 
            FROM trade_commands 
            WHERE status = 'pending' 
            ORDER BY created_at ASC
            LIMIT :limit
        """)
        result = db.execute(query, {"limit": limit})

        commands_list = []
        for row in result:
            commands_list.append({
                "command_id": str(row.id),
                "symbol": row.symbol,
                "side": str(row.order_type).upper(),
                "volume": float(row.lot_size),
                "sl": float(row.stop_loss) if row.stop_loss else 0.0,
                "tp": float(row.take_profit) if row.take_profit else 0.0
            })

        return commands_list
    except Exception as e:
        logger.error(f"❌ Error fetching commands: {e}")
        return []
    finally:
        db.close()

@router.post("/commands/{command_id}/ack")
async def ack_command(command_id: str, ea_id: str = None):
    db = SessionLocal()
    try:
        db.execute(text("UPDATE trade_commands SET status = 'processing' WHERE id = :id"), {"id": command_id})
        db.commit()
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error ack command {command_id}: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()

@router.post("/commands/{command_id}/report")
async def report_command(command_id: str, request: Request):
    db = SessionLocal()
    try:
        data = await request.json()
        status_val = data.get("status", "EXECUTED").lower()

        db.execute(text("UPDATE trade_commands SET status = :status WHERE id = :id"), 
                     {"status": status_val, "id": command_id})
        db.commit()
        logger.info(f"✅ Command {command_id} reported as {status_val.upper()}")
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error reporting command {command_id}: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()

@router.post("/commands")
async def receive_mt5_updates(request: Request):
    try:
        data = await request.json()
        logger.info(f"📥 MT5 Commands/Updates Received: {data}")
        return {"status": "success", "message": "Data received successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ==========================================
# 3. مسار مزامنة الحساب (Account Sync)
# ==========================================
@router.post("/account/sync")
async def sync_account(request: Request):
    db = SessionLocal()
    try:
        data = await request.json()
        account_data = data.get("account", {})

        account_number = account_data.get("login")
        balance = account_data.get("balance", 0.0)
        equity = account_data.get("equity", 0.0)
        margin = account_data.get("margin", 0.0)
        free_margin = account_data.get("free_margin", 0.0)
        profit = account_data.get("profit", equity - balance)

        margin_level = 0.0
        if margin > 0:
            margin_level = (equity / margin) * 100

        if account_number:
            query = text("""
                UPDATE trading_accounts 
                SET balance = :balance, 
                    equity = :equity, 
                    margin = :margin, 
                    free_margin = :free_margin, 
                    profit = :profit, 
                    margin_level = :margin_level, 
                    is_connected = True, 
                    last_sync = :last_sync
                WHERE account_number = :account_number
            """)
            db.execute(query, {
                "balance": balance,
                "equity": equity,
                "margin": margin,
                "free_margin": free_margin,
                "profit": profit,
                "margin_level": margin_level,
                "last_sync": datetime.utcnow().isoformat(),
                "account_number": account_number
            })
            db.commit()
            logger.info(f"✅ Database Updated via SQLAlchemy for account: {account_number} | Balance: {balance}")

        return {
            "status": "success", 
            "message": "Account data synced and updated in database successfully"
        }
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error in account sync: {str(e)}")
        return {
            "status": "error", 
            "message": str(e)
        }
    finally:
        db.close()

# ==========================================
# 4. مسار نبض الاتصال (Heartbeat) وتحديث الرصيد المباشر
# ==========================================
class AccountHeartbeat(BaseModel):
    account_number: int
    balance: float
    equity: float
    margin: float
    free_margin: float
    profit: float
    is_connected: bool

@router.post("/heartbeat")
async def account_heartbeat(account_data: AccountHeartbeat):
    db = SessionLocal()
    try:
        query = text("""
            UPDATE trading_accounts 
            SET balance = :balance, 
                equity = :equity, 
                margin = :margin, 
                free_margin = :free_margin, 
                profit = :profit, 
                is_connected = :is_connected, 
                last_heartbeat = :last_heartbeat
            WHERE account_number = :account_number
        """)
        db.execute(query, {
            "balance": account_data.balance,
            "equity": account_data.equity,
            "margin": account_data.margin,
            "free_margin": account_data.free_margin,
            "profit": account_data.profit,
            "is_connected": account_data.is_connected,
            "last_heartbeat": datetime.utcnow().isoformat(),
            "account_number": account_data.account_number
        })
        db.commit()
        return {
            "status": "success",
            "message": f"Heartbeat updated for account {account_data.account_number}"
        }
    except Exception as e:
        db.rollback()
        return {
            "status": "error",
            "message": str(e)
        }
    finally:
        db.close()
