from fastapi import APIRouter, Request
from pydantic import BaseModel
from datetime import datetime

# استدعاء الاتصال المباشر بقاعدة البيانات
from database import engine
from sqlalchemy import text

router = APIRouter(
    prefix="/api/v1/mt5",
    tags=["MT5 EA Integration"]
)

# ==========================================
# 1. مسار الأوامر (Commands) - النسخة الحقيقية للتنفيذ
# ==========================================
@router.get("/commands")
async def get_pending_commands(ea_id: str = None, limit: int = 10):
    try:
        with engine.begin() as conn:
            # سحب الأوامر المعلقة (pending) من قاعدة البيانات ليرسلها للروبوت
            query = text("""
                SELECT id, symbol, order_type, lot_size, stop_loss, take_profit 
                FROM trade_commands 
                WHERE status = 'pending' 
                ORDER BY created_at ASC
                LIMIT :limit
            """)
            result = conn.execute(query, {"limit": limit})
            
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
        print("❌ Error fetching commands:", e)
        return []

@router.post("/commands/{command_id}/ack")
async def ack_command(command_id: str, ea_id: str = None):
    try:
        with engine.begin() as conn:
            # بمجرد أن يستلم الروبوت الأمر، نغير حالته لـ processing حتى لا ينفذه مرتين
            conn.execute(text("UPDATE trade_commands SET status = 'processing' WHERE id = :id"), {"id": command_id})
        return {"status": "success"}
    except Exception as e:
        print(f"❌ Error ack command {command_id}:", e)
        return {"status": "error", "message": str(e)}

@router.post("/commands/{command_id}/report")
async def report_command(command_id: str, request: Request):
    try:
        data = await request.json()
        status_val = data.get("status", "EXECUTED").lower()
        with engine.begin() as conn:
            # تحديث حالة الأمر النهائية (تم التنفيذ بنجاح أو فشل)
            conn.execute(text("UPDATE trade_commands SET status = :status WHERE id = :id"), 
                         {"status": status_val, "id": command_id})
        print(f"✅ Command {command_id} reported as {status_val.upper()}")
        return {"status": "success"}
    except Exception as e:
        print(f"❌ Error reporting command {command_id}:", e)
        return {"status": "error", "message": str(e)}

@router.post("/commands")
async def receive_mt5_updates(request: Request):
    try:
        data = await request.json()
        print("📥 MT5 Commands/Updates Received:", data)
        return {"status": "success", "message": "Data received successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==========================================
# 2. مسار مزامنة الشموع والأسعار (Candles/Specs Sync) - مع الحفظ المزدوج
# ==========================================
@router.post("/candles/sync")
async def sync_candles(request: Request):
    try:
        data = await request.json()
        candles = data.get("candles", [])
        
        if not candles:
            return {"status": "success", "message": "No candles found in payload"}

        latest_candles = {}
        for c in candles:
            symbol = c.get("symbol")
            if symbol:
                latest_candles[symbol] = c

        with engine.begin() as conn:
            # 1. حفظ أسعار السوق الحية في جدول market_data
            for symbol, c in latest_candles.items():
                open_price = c.get("open", 0.0)
                close_price = c.get("close", 0.0)
                high_price = c.get("high", 0.0)
                low_price = c.get("low", 0.0)
                volume = c.get("volume", 0)

                change = close_price - open_price
                change_percent = (change / open_price * 100) if open_price > 0 else 0.0
                bid = close_price
                ask = close_price 

                update_query = text("""
                    UPDATE market_data 
                    SET bid = :bid, ask = :ask, high = :high, low = :low, 
                        volume = :volume, change = :change, change_percent = :change_percent, 
                        last_updated = :last_updated
                    WHERE symbol = :symbol
                """)
                result = conn.execute(update_query, {
                    "bid": bid, "ask": ask, "high": high_price, "low": low_price,
                    "volume": volume, "change": change, "change_percent": change_percent,
                    "last_updated": datetime.utcnow().isoformat(), "symbol": symbol
                })

                if result.rowcount == 0:
                    insert_query = text("""
                        INSERT INTO market_data 
                        (symbol, bid, ask, high, low, volume, change, change_percent, is_enabled, is_tradeable, last_updated)
                        VALUES 
                        (:symbol, :bid, :ask, :high, :low, :volume, :change, :change_percent, True, True, :last_updated)
                    """)
                    conn.execute(insert_query, {
                        "symbol": symbol, "bid": bid, "ask": ask, "high": high_price, "low": low_price,
                        "volume": volume, "change": change, "change_percent": change_percent,
                        "last_updated": datetime.utcnow().isoformat()
                    })
            
            # 2. حفظ تاريخ الشموع بالكامل في جدول candles من أجل الرسم البياني في فلاتر
            for c in candles:
                symbol = c.get("symbol")
                timeframe = c.get("timeframe")
                open_time = c.get("open_time")
                
                if not symbol or not timeframe or not open_time:
                    continue
                    
                candle_query = text("""
                    INSERT INTO candles (symbol_name, timeframe, open_time, open, high, low, close, volume)
                    VALUES (:sym, :tf, :ot, :o, :h, :l, :c, :v)
                    ON CONFLICT (symbol_name, timeframe, open_time) 
                    DO UPDATE SET 
                        open = EXCLUDED.open, 
                        high = EXCLUDED.high, 
                        low = EXCLUDED.low, 
                        close = EXCLUDED.close, 
                        volume = EXCLUDED.volume
                """)
                conn.execute(candle_query, {
                    "sym": symbol, "tf": timeframe, "ot": open_time,
                    "o": c.get("open"), "h": c.get("high"), "l": c.get("low"), "c": c.get("close"), "v": c.get("volume")
                })

        print(f"✅ Market Data & Candles Synced for {len(latest_candles)} symbols")
        return {"status": "success", "message": "Market data and candles synced successfully"}
    except Exception as e:
        print("❌ Error in candles sync:", str(e))
        return {"status": "error", "message": str(e)}

@router.post("/specs/sync")
async def sync_specs(request: Request):
    return {"status": "success", "message": "Symbol specifications synced"}

# ==========================================
# 3. مسار نبض الاتصال (Heartbeat) وتحديث الرصيد المباشر
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
    try:
        with engine.begin() as conn:
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
            conn.execute(query, {
                "balance": account_data.balance,
                "equity": account_data.equity,
                "margin": account_data.margin,
                "free_margin": account_data.free_margin,
                "profit": account_data.profit,
                "is_connected": account_data.is_connected,
                "last_heartbeat": datetime.utcnow().isoformat(),
                "account_number": account_data.account_number
            })

        return {
            "status": "success",
            "message": f"Heartbeat updated for account {account_data.account_number}"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

# ==========================================
# 4. مسار مزامنة الحساب (Account Sync)
# ==========================================
@router.post("/account/sync")
async def sync_account(request: Request):
    try:
        data = await request.json()
        print("📥 Account Sync Data Received:", data)

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
            with engine.begin() as conn:
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
                conn.execute(query, {
                    "balance": balance,
                    "equity": equity,
                    "margin": margin,
                    "free_margin": free_margin,
                    "profit": profit,
                    "margin_level": margin_level,
                    "last_sync": datetime.utcnow().isoformat(),
                    "account_number": account_number
                })
                
            print(f"✅ Database Updated via SQLAlchemy for account: {account_number} | Balance: {balance}")

        return {
            "status": "success", 
            "message": "Account data synced and updated in database successfully"
        }
    except Exception as e:
        print("❌ Error in account sync:", str(e))
        return {
            "status": "error", 
            "message": str(e)
        }
