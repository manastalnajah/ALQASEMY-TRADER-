from fastapi import APIRouter, Request
from pydantic import BaseModel
from datetime import datetime

# 🆕 استدعاء الاتصال المباشر بقاعدة البيانات (الموجود لديك بنجاح في ملف database)
from database import engine
from sqlalchemy import text

router = APIRouter(
    prefix="/api/v1/mt5",
    tags=["MT5 EA Integration"]
)

# ==========================================
# 1. مسار الأوامر (Commands)
# ==========================================
@router.get("/commands")
async def get_pending_commands(ea_id: str = None, limit: int = 10):
    return {
        "status": "success",
        "commands": []
    }

@router.post("/commands")
async def receive_mt5_updates(request: Request):
    try:
        data = await request.json()
        print("📥 MT5 Commands/Updates Received:", data)
        return {"status": "success", "message": "Data received successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ==========================================
# 2. مسار مزامنة الشموع والأسعار (Candles/Specs Sync) - مع الحفظ في قاعدة البيانات
# ==========================================
@router.post("/candles/sync")
async def sync_candles(request: Request):
    try:
        data = await request.json()
        candles = data.get("candles", [])
        
        if not candles:
            return {"status": "success", "message": "No candles found in payload"}

        # 1. تجميع آخر شمعة (السعر الحالي) لكل زوج عملات
        latest_candles = {}
        for c in candles:
            symbol = c.get("symbol")
            if symbol:
                # الكود سيستمر بتحديث الزوج حتى يصل لآخر شمعة (وهي الأحدث زمنياً)
                latest_candles[symbol] = c

        # 2. حفظ البيانات في جدول market_data عبر SQLAlchemy
        with engine.begin() as conn:
            for symbol, c in latest_candles.items():
                open_price = c.get("open", 0.0)
                close_price = c.get("close", 0.0)
                high_price = c.get("high", 0.0)
                low_price = c.get("low", 0.0)
                volume = c.get("volume", 0)

                # حساب التغير اليومي ونسبة التغير
                change = close_price - open_price
                change_percent = (change / open_price * 100) if open_price > 0 else 0.0

                # بما أن المنصة ترسل الشموع، سنعتبر سعر الإغلاق هو السعر الحالي (Bid/Ask)
                bid = close_price
                ask = close_price # يمكن إضافة فرق السبريد لاحقاً إذا أرسله الروبوت

                # محاولة تحديث الزوج إذا كان موجوداً مسبقاً
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

                # إذا لم يكن الزوج موجوداً في الجدول (rowcount == 0)، نقوم بإضافته لأول مرة
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
                    
        print(f"✅ Market Data Updated for {len(latest_candles)} symbols")
        return {"status": "success", "message": "Market data synced successfully"}
    except Exception as e:
        print("❌ Error in candles sync:", str(e))
        return {"status": "error", "message": str(e)}

@router.post("/specs/sync")
async def sync_specs(request: Request):
    return {"status": "success", "message": "Symbol specifications synced"}

# ==========================================
# 4. مسار مزامنة الحساب (Account Sync) - باستخدام SQLAlchemy المباشر
# ==========================================
@router.post("/account/sync")
async def sync_account(request: Request):
    try:
        data = await request.json()
        print("📥 Account Sync Data Received:", data)

        account_data = data.get("account", {})
        
        # استخراج البيانات بناءً على مفاتيح الروبوت الصحيحة
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
            # تحديث قاعدة البيانات باستخدام engine.begin() ليتم الحفظ (Commit) تلقائياً
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
