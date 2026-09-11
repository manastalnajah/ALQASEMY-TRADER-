from pydantic import BaseModel
from datetime import datetime

# 1. القالب الخاص باستقبال البيانات من تطبيق فلاتر أو الاستراتيجية
class CommandCreate(BaseModel):
    symbol: str
    order_type: str
    lot_size: float
    # 🔥 إضافة الحقول المفقودة لاستقبال الأسعار
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0

# 2. القالب الخاص بإرجاع البيانات (الرد) إلى الميتاتريدر وفلاتر
class CommandResponse(BaseModel):
    id: str  # 🔥 تم التعديل من int إلى str ليتوافق مع معرفات UUID
    symbol: str
    order_type: str
    lot_size: float
    status: str
    created_at: datetime
    # 🔥 إضافة الحقول المفقودة لإرسال الأسعار إلى الإكسبرت
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0

    # إعداد ضروري لكي تفهم Pydantic بيانات SQLAlchemy
    class Config:
        from_attributes = True
