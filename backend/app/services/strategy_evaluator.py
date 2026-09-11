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
    تأخذ بيانات السوق، تدير المخاطر بدقة، تفرض فترة انتظار آمنة، وتضمن صحة أسعار الدخول والحدود المتكيفة مع الإطار الزمني.
    """
    symbol = market_data.get("symbol")
    # 🔥 التعديل الأول: استخراج الإطار الزمني
    timeframe = market_data.get("timeframe", "M5").upper()
    
    if not symbol:
        return {"status": "error", "message": "Symbol is missing"}

    system_logger.info(f"🔄 بدء تقييم السوق لـ [{symbol}] على إطار [{timeframe}] باستخدام استراتيجية: {strategy_name}")

    # ==========================================
    # 🛡️ نظام الحماية الأول والثاني (منع التكدس و Cooldown)
    # ==========================================
    check_pending_query = text("""
        SELECT id FROM trade_commands 
        WHERE symbol = :symbol AND status IN ('pending', 'processing')
    """)
    if db.execute(check_pending_query, {"symbol": symbol}).fetchone():
        system_logger.warning(f"🛡️ حماية قصوى: يوجد أمر معلق أو قيد التنفيذ لـ [{symbol}]. تم تجاهل الإشارة.")
        return {"status": "ignored", "decision": "HOLD", "message": "Pending command exists"}

    check_cooldown_query = text("""
        SELECT id FROM trade_commands 
        WHERE symbol = :symbol AND created_at >= NOW() - INTERVAL '5 minutes'
    """)
    if db.execute(check_cooldown_query, {"symbol": symbol}).fetchone():
        system_logger.warning(f"🛡️ حماية الوقت (Cooldown): تم تنفيذ أمر مؤخراً لـ [{symbol}].")
        return {"status": "ignored", "decision": "HOLD", "message": "Cooldown active for 5 minutes"}

    # ==========================================
    # 🧠 استلام القرار الشامل من الاستراتيجية
    # ==========================================
    strategy_result = strategy_manager.execute(strategy_name, market_data)
    
    if isinstance(strategy_result, dict):
        decision = strategy_result.get("decision", "HOLD")
        entry_price = float(strategy_result.get("entry_price", 0.0))
        calculated_sl = float(strategy_result.get("sl", 0.0))
        calculated_tp = float(strategy_result.get("tp", 0.0))
    else:
        decision = strategy_result
        entry_price = 0.0
        calculated_sl = 0.0
        calculated_tp = 0.0

    if decision == "HOLD":
        return {"status": "success", "decision": "HOLD", "message": "No trade executed"}

    # ==========================================
    # 💰 إدارة المخاطر وتوسعة الحدود الديناميكية
    # ==========================================
    account = db.execute(text("SELECT balance, margin_level FROM trading_accounts LIMIT 1")).fetchone()
    balance = float(account.balance) if account and account.balance else 1000.0
    margin_level = float(account.margin_level) if account and account.margin_level else 0.0

    if 0 < margin_level < 300:
        system_logger.critical(f"⚠️ تحذير خطير: مستوى الهامش منخفض جداً ({margin_level}%). تم حظر الصفقات!")
        return {"status": "ignored", "decision": "HOLD", "message": "Low margin safety block"}

    base_lot = round((balance * 0.01) / 1000, 2)
    lot_size = max(0.01, min(0.1, base_lot / 10)) if symbol.upper() == "XAUUSD" else max(0.01, min(1.0, base_lot))
    pip_value = 0.1 if symbol.upper() == "XAUUSD" else (0.01 if "JPY" in symbol.upper() else 0.0001)
    current_price = float(market_data.get("close", 0.0))

    # 🔥 التعديل الثاني: مضاعف المسافة بناءً على الإطار الزمني
    tf_multiplier = 1.0
    if "H1" in timeframe:
        tf_multiplier = 2.5   # توسعة بنسبة 250% لإطار الساعة
    elif "H4" in timeframe:
        tf_multiplier = 4.0
    elif "D1" in timeframe:
        tf_multiplier = 8.0

    entry_buffer_pips = 15 * tf_multiplier
    sl_pips = 20 * tf_multiplier
    tp_pips = 40 * tf_multiplier

    # 🛠️ معالجة وتصحيح السعر
    if "LIMIT" in decision.upper() and entry_price <= 0.0 and current_price > 0:
        if decision.upper() == "BUY_LIMIT":
            entry_price = round(current_price - (entry_buffer_pips * pip_value), 5)
        elif decision.upper() == "SELL_LIMIT":
            entry_price = round(current_price + (entry_buffer_pips * pip_value), 5)
        system_logger.info(f"🔧 تصحيح سعر الدخول لـ [{symbol}]: {entry_price}")

    # حساب الوقف والهدف بالمسافات الديناميكية الجديدة
    if calculated_sl == 0.0 and current_price > 0:
        base_ref_price = entry_price if ("LIMIT" in decision.upper() and entry_price > 0) else current_price
        if "BUY" in decision.upper():
            calculated_sl = round(base_ref_price - (sl_pips * pip_value), 5)
            calculated_tp = round(base_ref_price + (tp_pips * pip_value), 5)
        elif "SELL" in decision.upper():
            calculated_sl = round(base_ref_price + (sl_pips * pip_value), 5)
            calculated_tp = round(base_ref_price - (tp_pips * pip_value), 5)

    system_logger.info(f"🛡️ المخاطر لـ [{symbol}]: النوع={decision} | الدخول={entry_price} | الوقف={calculated_sl} | الهدف={calculated_tp}")

    new_command = schemas.CommandCreate(
        symbol=symbol,
        order_type=decision,      
        lot_size=lot_size,
        entry_price=entry_price,
        stop_loss=calculated_sl,
        take_profit=calculated_tp
    )

    executed_command = trade_service.process_new_command(db=db, command=new_command)
    return {
        "status": "success", 
        "decision": decision, 
        "symbol": symbol,
        "command_id": executed_command.id
    }
