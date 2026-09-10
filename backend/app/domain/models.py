from sqlalchemy import Column, String, Float, DateTime
from datetime import datetime
# استدعاء Base من ملف قاعدة البيانات الذي أنشأناه في الجذر
from database import Base 

class TradeCommand(Base):
    __tablename__ = "trade_commands"  # ✅ توجيه الأوامر للجدول الصحيح

    # ✅ التعديل الجذري هنا: تغيير Integer إلى String ليتوافق مع الـ UUID في قاعدة البيانات
    id = Column(String, primary_key=True, index=True)
    
    symbol = Column(String, index=True)             # زوج العملات (مثل EURUSD أو XAUUSD)
    order_type = Column(String)                     # نوع الأمر (buy أو sell)
    lot_size = Column(Float)                        # حجم العقد (اللوت)
    status = Column(String, default="pending")      # حالة الأمر (pending, executed, failed)
    created_at = Column(DateTime, default=datetime.utcnow) # وقت الإرسال
