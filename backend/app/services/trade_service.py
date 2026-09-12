import time
import logging
from sqlalchemy import text
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.config import config
from app.domain import schemas
from app.repositories.trade_repo import TradeRepository
from app.logging.logger import system_logger
from app.services.risk_manager import validate_and_size

# تم إضافة أوامر الـ STOP لتتطابق مع EA v14.0
VALID_TYPES = {"BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}

def process_new_command(
    db: Session, 
    command: schemas.CommandCreate, 
    account_id: str,  # إضافة إلزامية لتمرير هوية الحساب
    *, 
    enforce_risk: bool = True
):
    command.symbol = command.symbol.upper()
    command.order_type = command.order_type.upper()
    command.account_id = account_id  # ربط الأمر بالحساب لتجنب فشل الـ Migration

    if command.order_type not in VALID_TYPES:
        raise HTTPException(400, "نوع الأمر غير مسموح")
    if command.entry_price <= 0 or command.stop_loss <= 0 or command.take_profit <= 0:
        raise HTTPException(400, "SL وTP وسعر الدخول مطلوبة ولا يجوز أن تكون صفراً")
    if command.lot_size <= 0:
        raise HTTPException(400, "حجم اللوت يجب أن يكون أكبر من صفر")

    # تأمين مفتاح الإشارة للأوامر اليدوية بطابع زمني لمنع التصادم في قاعدة البيانات
    if not command.signal_key:
        timestamp = int(time.time())
        command.signal_key = f"manual:{command.symbol}:{command.order_type}:{command.entry_price:.5f}:{timestamp}"

    # Manual/API commands are also protected. The strategy is never allowed to bypass this gate.
    if enforce_risk:
        sized, reason = validate_and_size(
            db,
            account_id=account_id,  # تمرير الحساب ليتم الخصم/التحقق من risk_state الخاص به
            symbol=command.symbol,
            order_type=command.order_type,
            entry=command.entry_price,
            stop=command.stop_loss,
            target=command.take_profit,
            signal_key=command.signal_key,
        )
        if not sized:
            system_logger.warning("🛑 رفض أمر %s %s: %s", command.order_type, command.symbol, reason)
            raise HTTPException(409, f"Trade blocked by risk engine: {reason}")
        
        # The risk engine owns the authoritative lot size. The caller cannot choose a larger or smaller risk budget.
        command.lot_size = float(sized["lot_size"])
        if command.lot_size <= 0:
            raise HTTPException(409, "Trade blocked: calculated risk size is zero")

    repo = TradeRepository(db)
    try:
        command_obj = repo.create_trade_command(command)
        system_logger.info("✅ Command created: %s %s %.4f for account %s", 
                           command.symbol, command.order_type, command.lot_size, account_id)
        return command_obj
    except Exception as e:
        db.rollback()
        system_logger.error("❌ Failed to save command: %s", str(e))
        raise
