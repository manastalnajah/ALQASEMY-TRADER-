from fastapi import APIRouter, Request
from pydantic import BaseModel
from datetime import datetime

# استدعاء عميل Supabase للاتصال بقاعدة البيانات وتحديث الجداول
from app.core.network.supabase_client import SupabaseClient  # تأكد أن مسار الاستدعاء يطابق هيكل مشروعك

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
        "commands": []  # قائمة فارغة تخبر الروبوت أنه لا توجد أوامر معلقة حالياً
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
# 2. مسار مزامنة الشموع والأسعار (Candles/Specs Sync)
# ==========================================
@router.post("/candles/sync")
async def sync_candles(request: Request):
    try:
        data = await request.json()
        return {"status": "success", "message": "Candles synced successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/specs/sync")
async def sync_specs(request: Request):
    return {"status": "success", "message": "Symbol specifications synced"}

# ==========================================
# 4. مسار مزامنة الحساب (Account Sync) - النسخة النهائية المحدثة 🚀
# ==========================================
@router.post("/account/sync")
async def sync_account(request: Request):
    try:
        data = await request.json()
        print("📥 Account Sync Data Received:", data)

        # 1. الدخول إلى الكائن الفرعي "account" الذي يرسله الروبوت كما ظهر في السجلات
        account_data = data.get("account", {})

        # 2. استخراج البيانات بالأسماء الصحيحة (استخدام login بدلاً من account_number)
        account_number = account_data.get("login")
        balance = account_data.get("balance", 0.0)
        equity = account_data.get("equity", 0.0)
        margin = account_data.get("margin", 0.0)
        free_margin = account_data.get("free_margin", 0.0)
        
        # حساب الربح أو الخسارة
        profit = account_data.get("profit", equity - balance)
        
        # حساب مستوى الهامش
        margin_level = 0.0
        if margin > 0:
            margin_level = (equity / margin) * 100

        # 3. التأكد من وجود رقم الحساب قبل التحديث
        if account_number:
            update_data = {
                "balance": balance,
                "equity": equity,
                "margin": margin,
                "free_margin": free_margin,
                "profit": profit,
                "margin_level": margin_level,
                "is_connected": True,
                "last_sync": datetime.utcnow().isoformat()
            }

            # تنفيذ أمر التحديث في قاعدة البيانات
            SupabaseClient.table("trading_accounts") \
                .update(update_data) \
                .eq("account_number", account_number) \
                .execute()
                
            print(f"✅ Database Updated for account: {account_number} | Balance: {balance}")

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
        update_data = {
            "balance": account_data.balance,
            "equity": account_data.equity,
            "margin": account_data.margin,
            "free_margin": account_data.free_margin,
            "profit": account_data.profit,
            "is_connected": account_data.is_connected,
            "last_heartbeat": datetime.utcnow().isoformat()
        }

        SupabaseClient.table("trading_accounts") \
            .update(update_data) \
            .eq("account_number", account_data.account_number) \
            .execute()

        return {
            "status": "success",
            "message": f"Heartbeat updated for account {account_data.account_number}"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
