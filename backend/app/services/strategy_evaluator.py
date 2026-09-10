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
    تأخذ بيانات السوق، تدير المخاطر بدقة، تفرض فترة انتظار آمنة، وتضمن صحة أسعار الدخول والحدود.
    """
    symbol = market_data.get("symbol")
    if not symbol:
        return {"status": "error", "message": "Symbol is missing"}

    system_logger.info(f"🔄 بدء تقييم السوق لـ [{symbol}] باستخدام استراتيجية: {strategy_name}")

    # ==========================================
    # 🛡️ نظام الحماية الأول: التحقق التام من وجود أمر معلق أو قيد المعالجة
    # ==========================================
    check_pending_query = text("""
        SELECT id FROM trade_commands 
        WHERE symbol = :symbol AND status IN ('pending', 'processing')
    """)
    is_pending = db.execute(check_pending_query, {"symbol": symbol}).fetchone()
    
    if is_pending:
        system_logger.warning(f"🛡️ حماية قصوى: يوجد أمر معلق أو قيد التنفيذ لـ [{symbol}]. تم تجاهل الإشارة تماماً لمنع التكدس.")
        return {"status": "ignored", "decision": "HOLD", "message": "Pending command exists"}

    # ==========================================
    # 🛡️ نظام الحماية الثاني: حظر مؤقت صارم (Cooldown) لمدة 5 دقائق كاملة
    # ==========================================
    check_cooldown_query = text("""
        SELECT id FROM trade_commands 
        WHERE symbol = :symbol 
        AND created_at >= NOW() - INTERVAL '5 minutes'
    """)
    cooldown_check = db.execute(check_cooldown_query, {"symbol": symbol}).fetchone()
    
    if cooldown_check:
        system_logger.warning(f"🛡️ حماية الوقت (Cooldown): تم تنفيذ أمر مؤخراً لـ [{symbol}]. يجب الانتظار 5 دقائق بين الصفقات.")
        return {"status": "ignored", "decision": "HOLD", "message": "Cooldown active for 5 minutes"}

    # ==========================================
    # 🧠 استلام القرار الشامل من الاستراتيجية (دعم الأوامر المعلقة والحدود)
    # ==========================================
    strategy_result = strategy_manager.execute(strategy_name, market_data)
    
    # التعامل مع الرد (سواء كان قاموساً يحتوي على تفاصيل الحد أو نصاً مباشراً)
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

    # إذا كان القرار هو الانتظار (HOLD)، ننهي العملية بصمت
    if decision == "HOLD":
        return {"status": "success", "decision": "HOLD", "message": "No trade executed"}

    # ==========================================
    # 💰 وحدة إدارة المخاطر والتحكم في رأس المال
    # ==========================================
    account = db.execute(text("SELECT balance, margin_level FROM trading_accounts LIMIT 1")).fetchone()
    
    balance = 1000.0  # قيمة افتراضية
    margin_level = 0.0

    if account:
        balance = float(account.balance or 1000.0)
        margin_level = float(account.margin_level or 0.0)
        
        # مكابح الطوارئ للهامش
        if margin_level > 0 and margin_level < 300:
            system_logger.critical(f"⚠️ تحذير خطير: مستوى الهامش منخفض جداً ({margin_level}%). تم حظر فتح صفقات جديدة!")
            return {"status": "ignored", "decision": "HOLD", "message": "Low margin safety block"}

    # حساب حجم العقد (Lot Size) بناءً على نسبة مخاطرة 1%
    risk_percentage = 0.01 
    base_lot = round((balance * risk_percentage) / 1000, 2)
    
    if symbol.upper() == "XAUUSD":
        lot_size = max(0.01, min(0.1, base_lot / 10))
    else:
        lot_size = max(0.01, min(1.0, base_lot))

    # حساب قيمة النقطة
    pip_value = 0.01 if "JPY" in symbol.upper() else 0.0001
    if symbol.upper() == "XAUUSD":
        pip_value = 0.1

    current_price = float(market_data.get("close", 0.0))

    # ==========================================
    # 🛠️ معالجة وتصحيح سعر الدخول (Entry Price) للأوامر المعلقة لمنع خطأ invalid price
    # ==========================================
    if "LIMIT" in decision.upper() and entry_price <= 0.0 and current_price > 0:
        if decision.upper() == "BUY_LIMIT":
            entry_price = round(current_price - (15 * pip_value), 5) # سعر معلق أسفل السعر الحالي
        elif decision.upper() == "SELL_LIMIT":
            entry_price = round(current_price + (15 * pip_value), 5) # سعر معلق أعلى السعر الحالي
        system_logger.info(f"🔧 تصحيح تلقائي لسعر الدخول لـ [{symbol}] ({decision}): تم ضبط السعر عند {entry_price}")

    # إذا لم تحدد الاستراتيجية الوقف والهدف، نحسبهما ديناميكياً كاحتياط
    if calculated_sl == 0.0 and current_price > 0:
        base_ref_price = entry_price if ("LIMIT" in decision.upper() and entry_price > 0) else current_price
        if "BUY" in decision.upper():
            calculated_sl = round(base_ref_price - (20 * pip_value), 5)
            calculated_tp = round(base_ref_price + (40 * pip_value), 5)
        elif "SELL" in decision.upper():
            calculated_sl = round(base_ref_price + (20 * pip_value), 5)
            calculated_tp = round(base_ref_price - (40 * pip_value), 5)

    # ==========================================
    # تجهيز وإرسال الأمر
    # ==========================================
    system_logger.info(f"🛡️ إدارة المخاطر لـ [{symbol}]: النوع={decision} | الرصيد={balance} | اللوت={lot_size} | الدخول={entry_price} | الوقف={calculated_sl} | الهدف={calculated_tp}")

    new_command = schemas.CommandCreate(
        symbol=symbol,
        order_type=decision,      
        lot_size=lot_size,
        entry_price=entry_price,  # 👈 مُضمن الآن بقيمة صحيحة ومضبوطة تماماً
        stop_loss=calculated_sl,
        take_profit=calculated_tp
    )

    # إرسال الأمر والحفظ في جدول trade_commands
    executed_command = trade_service.process_new_command(db=db, command=new_command)
    system_logger.info(f"✅ تم إنشاء أمر ذكي لـ [{symbol}] | النوع: {decision} | رقم الأمر: {executed_command.id}")

    return {
        "status": "success", 
        "decision": decision, 
        "symbol": symbol,
        "command_id": executed_command.id
    }
