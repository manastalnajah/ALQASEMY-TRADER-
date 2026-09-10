from sqlalchemy import Column, String, Float, DateTime
from datetime import datetime
# استدعاء Base من ملف قاعدة البيانات الذي أنشأناه في الجذر
from database import Base 

class TradeCommand(Base):
    __tablename__ = "trade_commands"  # ✅ توجيه الأوامر للجدول الصحيح

    # ✅ التعديل الحاسم هنا: إخبار SQLAlchemy بألا تتوقع توليداً تلقائياً، لأن بايثون سيمرر الـ UUID جاهزاً
    id = Column(String, primary_key=True, index=True, autoincrement=False)
    
    symbol = Column(String, index=True)             # زوج العملات (مثل EURUSD أو XAUUSD)
    order_type = Column(String)                     # نوع الأمر (buy, sell, buy_limit, sell_limit)
    lot_size = Column(Float)                        # حجم العقد (اللوت)
    entry_price = Column(Float, default=0.0)        # سعر الدخول للأوامر المعلقة
    stop_loss = Column(Float, default=0.0)          # وقف الخسارة
    take_profit = Column(Float, default=0.0)        # جني الأرباح
    status = Column(String, default="pending")      # حالة الأمر (pending, executed, failed)
    created_at = Column(DateTime, default=datetime.utcnow) # وقت الإرسال
