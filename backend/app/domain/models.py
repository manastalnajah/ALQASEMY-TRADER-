from sqlalchemy import Column, String, Float, DateTime, Integer, text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID  # الاستيراد الصحيح ليتوافق مع نوع UUID
from datetime import datetime
from database import Base 

class TradeCommand(Base):
    __tablename__ = "trade_commands"  

    # استخدام UUID(as_uuid=True) لمطابقة نوع القاعدة 100%
    id = Column(UUID(as_uuid=True), primary_key=True, index=True, server_default=text("uuid_generate_v4()"))
    
    symbol = Column(String, index=True)             # زوج العملات (مثل EURUSD أو XAUUSD)
    order_type = Column(String)                     # نوع الأمر (buy, sell, buy_limit, sell_limit)
    lot_size = Column(Float)                        # حجم العقد (اللوت)
    entry_price = Column(Float, default=0.0)        # سعر الدخول للأوامر المعلقة
    stop_loss = Column(Float, default=0.0)          # وقف الخسارة
    take_profit = Column(Float, default=0.0)        # جني الأرباح
    status = Column(String, default="pending")      # حالة الأمر (pending, executed, failed)
    created_at = Column(DateTime, default=datetime.utcnow) # وقت الإرسال


# ==========================================
# 📊 إضافة نموذج جدول الشموع (Candles) مع الحماية
# ==========================================
class Candle(Base):
    __tablename__ = "candles"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True, server_default=text("uuid_generate_v4()"))
    symbol_name = Column(String, index=True, nullable=False)
    
    # 🔥 التعديل الأول: إضافة عمود الإطار الزمني
    timeframe = Column(String, index=True, nullable=False, default="M5") 
    
    open_time = Column(String, index=True, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Integer, nullable=False)

    # 🔥 التعديل الثاني والحاسم: قيد فريد مركب (Composite Unique Constraint)
    # هذا القيد يمنع تكرار الشمعة لنفس الزوج ونفس الإطار الزمني في نفس الوقت
    # ويتطابق تماماً مع عبارة ON CONFLICT في الباك اند
    __table_args__ = (
        UniqueConstraint('symbol_name', 'timeframe', 'open_time', name='uix_symbol_timeframe_time'),
    )
