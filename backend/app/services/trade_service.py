from sqlalchemy.orm import Session
from fastapi import HTTPException
# استدعاء القوالب 
from app.domain import schemas
# استدعاء الفئة (Class) الخاصة بالمستودع
from app.repositories.trade_repo import TradeRepository
# استدعاء المراقب (Logger)
from app.logging.logger import system_logger

def process_new_command(db: Session, command: schemas.CommandCreate):
    """
    هذه الدالة تمثل 'نقطة التفتيش' وإدارة المخاطر (Risk Management).
    أي أمر قادم من الاستراتيجيات سيمر من هنا أولاً قبل أن يصل لقاعدة البيانات.
    """
    
    # تسجيل حدث استلام أمر جديد
    system_logger.info(f"📥 استلام أمر جديد للتدقيق: {command.order_type} {command.symbol} بحجم لوت {command.lot_size}")
    
    # 1. شرط الأمان الأول: التحقق من حجم اللوت (Lot Size)
    if command.lot_size <= 0 or command.lot_size > 50:
        system_logger.warning(f"⚠️ تم رفض الأمر: حجم اللوت ({command.lot_size}) غير مسموح به!")
        raise HTTPException(
            status_code=400, 
            detail="⚠️ خطأ: حجم اللوت غير مسموح! يجب أن يكون بين 0.01 و 50"
        )
        
    # 2. شرط الأمان الثاني: التحقق من نوع الأمر (تمت إضافة الأوامر المعلقة Limit / Stop)
    order_type_lower = command.order_type.lower()
    valid_order_types = ["buy", "sell", "buy_limit", "sell_limit", "buy_stop", "sell_stop"]
    
    if order_type_lower not in valid_order_types:
        system_logger.warning(f"⚠️ تم رفض الأمر: نوع الأمر ({command.order_type}) غير معروف!")
        raise HTTPException(
            status_code=400, 
            detail="⚠️ خطأ: نوع الأمر يجب أن يكون مباشر (buy/sell) أو أمر معلق صحيح (Limit/Stop)"
        )
        
    # 3. توحيد صيغة رمز العملة
    command.symbol = command.symbol.upper()

    # تسجيل حدث نجاح الفحص
    system_logger.info("✅ اجتاز الأمر شروط الأمان بنجاح، جاري الحفظ في قاعدة البيانات...")

    # إنشاء نسخة من المستودع وربطها بقاعدة البيانات
    repo = TradeRepository(db)
    
    # إرسال الأمر للحفظ في المستودع (مع دعم entry_price, sl, tp)
    return repo.create_trade_command(command=command)
