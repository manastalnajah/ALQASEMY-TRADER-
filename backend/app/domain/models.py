from sqlalchemy import Column, Integer, String, Float, DateTime
from datetime import datetime
# استدعاء Base من ملف قاعدة البيانات الذي أنشأناه في الجذر
from database import Base 

class TradeCommand(Base):
    __tablename__ = "trade_commands"  # ✅ التصحيح الحاسم: توجيه الأوامر للجدول الصحيح

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)             # زوج العملات (مثل EURUSD أو XAUUSD)
    order_type = Column(String)                     # نوع الأمر (buy أو sell)
    lot_size = Column(Float)                        # حجم العقد (اللوت)
    status = Column(String, default="pending")    # حالة الأمر (pending, executed, failed)
    created_at = Column(DateTime, default=datetime.utcnow) # وقت الإرسال
