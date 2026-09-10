from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.strategies.strategy_manager import manager as strategy_manager
from app.services import trade_service
from app.domain import schemas
from app.logging.logger import system_logger

def evaluate_and_execute_strategy(db: Session, strategy_name: str, market_data: dict):
    """
    هذه الخدمة هي حلقة الوصل المباشرة. 
    تأخذ بيانات السوق، تسأل الاستراتيجية عن رأيها، وإذا كان القرار إيجابياً تفتح الصفقة.
    تدعم تلقائياً وبكفاءة جميع الأسواق المتاحة (مثل XAUUSD للذهب و EURUSD لليورو).
    """
    # استخراج الرمز بمرونة وتأمين عدم حدوث خطأ إذا كان مفقوداً
    symbol = market_data.get("symbol")
    if not symbol:
        system_logger.error("❌ خطأ: لم يتم العثور على رمز السوق (Symbol) في بيانات التحليل!")
        return {"status": "error", "message": "Symbol is missing"}

    system_logger.info(f"🔄 بدء تقييم السوق لـ [{symbol}] باستخدام استراتيجية: {strategy_name}")

    # 1. إرسال البيانات لمدير الاستراتيجيات لتحليلها
    decision = strategy_manager.execute(strategy_name, market_data)

    # 2. إذا كان القرار هو الانتظار (HOLD)، ننهي العملية بصمت
    if decision == "HOLD":
        system_logger.info(f"⏳ قرار الاستراتيجية لـ [{symbol}]: الانتظار (HOLD). لا توجد فرص حالياً.")
        return {"status": "success", "decision": "HOLD", "message": "No trade executed"}

    # 3. إذا كان القرار (BUY) أو (SELL)، نجهز أمر التداول بدقة
    system_logger.info(f"⚡ قرار الاستراتيجية لـ [{symbol}]: {decision}! جاري تجهيز أمر التداول...")
    
    # تخصيص حجم اللوت تلقائياً حسب طبيعة السوق لحماية الحساب:
    # الذهب (XAUUSD) يتحرك بنقاط كبيرة، لذا يفضل عقد أصغر (0.01)، والعملات (EURUSD) تستخدم (0.1)
    lot_size = 0.01 if symbol.upper() == "XAUUSD" else 0.1

    # تجهيز قالب الأمر (Command) مع الرمز الحي الصحيح (سواء ذهب أو يورو)
    new_command = schemas.CommandCreate(
        symbol=symbol,
        order_type=decision,
        lot_size=lot_size
    )

    # 4. إرسال الأمر إلى نقطة التفتيش (Trade Service) ليتم اعتماده وحفظه في جدول trade_commands الصحيح
    executed_command = trade_service.process_new_command(db=db, command=new_command)

    system_logger.info(f"✅ تم إنشاء أمر جديد بنجاح لـ [{symbol}] | النوع: {decision} | اللوت: {lot_size} | رقم الأمر: {executed_command.id}")

    return {
        "status": "success", 
        "decision": decision, 
        "symbol": symbol,
        "command_id": executed_command.id
    }
