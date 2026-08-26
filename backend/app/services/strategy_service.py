from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.strategies.strategy_manager import manager as strategy_manager
from app.services import trade_service
from app.domain import schemas
from app.logging.logger import system_logger

def evaluate_and_execute_strategy(db: Session, strategy_name: str, market_data: dict):
    """
    هذه الخدمة هي حلقة الوصل المباشرة. 
    تأخذ بيانات السوق، تسأَل الاستراتيجية عن رأيها، وإذا كان القرار إيجابياً تفتح الصفقة.
    """
    system_logger.info(f"🔄 بدء تقييم السوق باستخدام استراتيجية: {strategy_name}")

    # 1. إرسال البيانات لمدير الاستراتيجيات لتحليلها
    decision = strategy_manager.execute(strategy_name, market_data)

    # 2. إذا كان القرار هو الانتظار (HOLD)، ننهي العملية بصمت
    if decision == "HOLD":
        system_logger.info("⏳ قرار الاستراتيجية: الانتظار (HOLD). لا توجد فرص حالياً.")
        return {"status": "success", "decision": "HOLD", "message": "No trade executed"}

    # 3. إذا كان القرار (BUY) أو (SELL)، نجهز أمر التداول
    system_logger.info(f"⚡ قرار الاستراتيجية: {decision}! جاري تجهيز أمر التداول...")
    
    # تجهيز قالب الأمر (Command) كما يطلبه النظام
    # ملاحظة: حجم اللوت هنا (0.1) يمكن تغييره لاحقاً ليُقرأ من إعدادات المستخدم في قاعدة البيانات
    new_command = schemas.CommandCreate(
        symbol=market_data.get("symbol", "EURUSD"),
        order_type=decision,
        lot_size=0.1  
    )

    # 4. إرسال الأمر إلى نقطة التفتيش (Trade Service) ليتم اعتماده وحفظه
    executed_command = trade_service.process_new_command(db=db, command=new_command)

    return {
        "status": "success", 
        "decision": decision, 
        "command_id": executed_command.id
    }