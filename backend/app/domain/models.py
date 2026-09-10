from sqlalchemy import Column, String, Float, DateTime
from datetime import datetime
from database import Base 

class TradeCommand(Base):
    __tablename__ = "trade_commands"

    # 👈 اترك SQLAlchemy تدير الـ id وتتوقع توليده تلقائياً من القاعدة
    id = Column(String, primary_key=True, index=True)
    
    symbol = Column(String, index=True)
    order_type = Column(String)
    lot_size = Column(Float)
    entry_price = Column(Float, default=0.0)
    stop_loss = Column(Float, default=0.0)
    take_profit = Column(Float, default=0.0)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
