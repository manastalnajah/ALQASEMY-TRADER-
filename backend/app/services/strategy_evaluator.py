from sqlalchemy.orm import Session
from sqlalchemy import text
from fastapi import HTTPException
from app.strategies.strategy_manager import manager as strategy_manager
from app.services import trade_service
from app.domain import schemas
from app.logging.logger import system_logger

def evaluate_and_execute_strategy(db: Session, strategy_name: str, market_data: dict):
    """
    هذه الخدمة هي حلقة الوصل المباشرة. 
    تأخذ بيانات السوق، تسأل الاستراتيجية، تمنع التكرار العشوائي، وتفتح الصفقة بأمان.
    """
    symbol = market_data.get("symbol")
    if not symbol:
        return {"status": "error", "message": "Symbol is missing"}

    system_logger.info(f"🔄 بدء تقييم السوق لـ [{symbol}] باستخدام استراتيجية: {strategy_name}")

    # ==========================================
    # 🛡️ نظام الحماية: التحقق من الأوامر المعلقة
    # ==========================================
    # نمنع البوت من إصدار إشارة جديدة إذا كان هناك أمر معلق أو جاري تنفيذه لنفس الرمز
    check_pending_query = text("""
        SELECT id FROM trade_commands 
        WHERE symbol = :symbol AND status IN ('pending', 'processing')
    """)
    is_pending = db.execute(check_pending_query, {"symbol": symbol}).fetchone()
    
    if is_pending:
        system_logger.warning(f"🛡️ حماية: يوجد أمر لم ينفذ بعد لـ [{symbol}]. تم تجاهل الإشارة لمنع التكدس.")
        return {"status": "ignored", "decision": "HOLD", "message": "Pending command exists"}

    # 1. إرسال البيانات لمدير الاستراتيجيات لتحليلها
    decision = strategy_manager.execute(strategy_name, market_data)

    # 2. إذا كان القرار هو الانتظار (HOLD)، ننهي العملية بصمت
    if decision == "HOLD":
        return {"status": "success", "decision": "HOLD", "message": "No trade executed"}

    # ==========================================
    # 🛡️ نظام الحماية: منع فتح صفقات متكررة في نفس الاتجاه
    # ==========================================
    # نمنع البوت من فتح صفقة شراء جديدة إذا كان قد فتح صفقة شراء بالفعل قبل وقت قريب
    check_executed_query = text("""
        SELECT id FROM trade_commands 
        WHERE symbol = :symbol 
        AND order_type = :decision 
        AND status = 'executed' 
        AND created_at >= NOW() - INTERVAL '1 hour' -- يمنع فتح صفقة بنفس الاتجاه لمدة ساعة من آخر إشارة
    """)
    recently_executed = db.execute(check_executed_query, {"symbol": symbol, "decision": decision}).fetchone()

    if recently_executed:
        system_logger.warning(f"🛡️ حماية: البوت قام بفتح صفقة {decision} لـ [{symbol}] مسبقاً. لن يتم فتح صفقة أخرى لتجنب المخاطرة المتكررة.")
        return {"status": "ignored", "decision": "HOLD", "message": "Trade already opened recently"}

    # 3. إذا مر من الحماية والقرار (BUY) أو (SELL)، نجهز أمر التداول
    system_logger.info(f"⚡ قرار الاستراتيجية لـ [{symbol}]: {decision}! جاري تجهيز أمر التداول...")
    
    lot_size = 0.01 if symbol.upper() == "XAUUSD" else 0.1

    new_command = schemas.CommandCreate(
        symbol=symbol,
        order_type=decision,
        lot_size=lot_size
    )

    # 4. إرسال الأمر للحفظ
    executed_command = trade_service.process_new_command(db=db, command=new_command)
    system_logger.info(f"✅ تم إنشاء أمر جديد بأمان لـ [{symbol}] | النوع: {decision} | رقم الأمر: {executed_command.id}")

    return {
        "status": "success", 
        "decision": decision, 
        "symbol": symbol,
        "command_id": executed_command.id
    }
