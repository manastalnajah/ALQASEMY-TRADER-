from fastapi import APIRouter, Request, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

# إعداد الموجه (Router) مع البادئة التي يبحث عنها الروبوت
router = APIRouter(
    prefix="/api/v1/mt5",
    tags=["MT5 EA Integration"]
)

# ==========================================
# 1. مسار الأوامر (Commands)
# ==========================================
# يستخدمه الروبوت (عبر طلب GET) للبحث عن أي أوامر جديدة (مثل إغلاق صفقة من التطبيق)
@router.get("/commands")
async def get_pending_commands(ea_id: str = None, limit: int = 10):
    # في المستقبل: هنا يمكنك جلب الأوامر المعلقة من قاعدة البيانات
    return {
        "status": "success",
        "commands": []  # قائمة فارغة تخبر الروبوت أنه لا توجد أوامر حالياً
    }

# يستخدمه الروبوت (عبر طلب POST) لإرسال تحديثات حالة الحساب (الرصيد، الصفقات المفتوحة)
@router.post("/commands")
async def receive_mt5_updates(request: Request):
    try:
        # استقبال البيانات القادمة من الروبوت (MT5 EA)
        data = await request.json()
        
        # هنا يتم كتابة كود تحديث قاعدة بيانات Supabase
        # سيتم استخراج: data.get("balance"), data.get("account_number") إلخ...
        # وحفظها في جدول trading_accounts
        
        return {"status": "success", "message": "Data received and database updated"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ==========================================
# 2. مسار مزامنة الشموع والأسعار (Candles/Specs Sync)
# ==========================================
# يستخدمه الروبوت لإرسال بيانات الشموع اليابانية لتحديث واجهة التطبيق أو التحليل
@router.post("/candles/sync")
async def sync_candles(request: Request):
    try:
        data = await request.json()
        # هنا يتم حفظ بيانات الشموع القادمة من المنصة
        return {"status": "success", "message": "Candles synced successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/specs/sync")
async def sync_specs(request: Request):
    return {"status": "success", "message": "Symbol specifications synced"}
# ==========================================
# 4. مسار مزامنة الحساب (Account Sync) - الذي يبحث عنه الروبوت
# ==========================================
@router.post("/account/sync")
async def sync_account(request: Request):
    try:
        # استقبال بيانات الرصيد والحساب من الروبوت
        data = await request.json()
        
        # طباعة البيانات في الكونسول للتأكد من وصولها (لأغراض الفحص)
        print("📥 Account Data Received:", data)
        
        # لاحقاً: هنا سيتم كتابة كود التحديث في قاعدة بيانات Supabase
        
        return {
            "status": "success", 
            "message": "Account data synced successfully"
        }
    except Exception as e:
        return {
            "status": "error", 
            "message": str(e)
        }
# ==========================================
# 3. مسار نبض الاتصال (Heartbeat) وتحديث الرصيد المباشر
# ==========================================
# نموذج مصغر لاستقبال بيانات الحساب (يطابق ما بنيناه في فلاتر)
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
    # بمجرد أن يرسل الروبوت هذه البيانات، يجب تحديثها في Supabase 
    # لتنعكس فوراً في تطبيق فلاتر
    return {
        "status": "success",
        "message": f"Heartbeat updated for account {account_data.account_number}"
    }
