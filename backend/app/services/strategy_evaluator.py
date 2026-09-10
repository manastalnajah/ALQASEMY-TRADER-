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
    تأخذ بيانات السوق، تدير المخاطر ورأس المال، تمنع التكرار، وتفتح الصفقة بحماية كاملة.
    """
    symbol = market_data.get("symbol")
    if not symbol:
        return {"status": "error", "message": "Symbol is missing"}

    system_logger.info(f"🔄 بدء تقييم السوق لـ [{symbol}] باستخدام استراتيجية: {strategy_name}")

    # ==========================================
    # 🛡️ نظام الحماية الأول: التحقق من الأوامر المعلقة لمنع التكدس
    # ==========================================
    check_pending_query = text("""
        SELECT id FROM trade_commands 
        WHERE symbol = :symbol AND status IN ('pending', 'processing')
    """)
    is_pending = db.execute(check_pending_query, {"symbol": symbol}).fetchone()
    
    if is_pending:
        system_logger.warning(f"🛡️ حماية: يوجد أمر لم ينفذ بعد لـ [{symbol}]. تم تجاهل الإشارة لمنع التكدس.")
        return {"status": "ignored", "decision": "HOLD", "message": "Pending command exists"}

    # ==========================================
    # 🛡️ نظام الحماية الثاني: مانع التكرار السريع (Anti-Spam Cooldown)
    # ==========================================
    check_spam_query = text("""
        SELECT id FROM trade_commands 
        WHERE symbol = :symbol 
        AND created_at >= NOW() - INTERVAL '1 minute'
    """)
    spam_check = db.execute(check_spam_query, {"symbol": symbol}).fetchone()
    
    if spam_check:
        system_logger.warning(f"🛡️ حماية ضد التكرار: تم إصدار أمر قريب جداً لـ [{symbol}]. جاري الانتظار...")
        return {"status": "ignored", "decision": "HOLD", "message": "Cooldown active"}

    # 1. إرسال البيانات لمدير الاستراتيجيات لتحليلها
    decision = strategy_manager.execute(strategy_name, market_data)

    # 2. إذا كان القرار هو الانتظار (HOLD)، ننهي العملية بصمت
    if decision == "HOLD":
        return {"status": "success", "decision": "HOLD", "message": "No trade executed"}

    # ==========================================
    # 🧠 وحدة إدارة المخاطر والتحكم في رأس المال
    # ==========================================
    # جلب رصيد الحساب ومستوى الهامش المباشر من جدول trading_accounts
    account = db.execute(text("SELECT balance, margin_level FROM trading_accounts LIMIT 1")).fetchone()
    
    balance = 1000.0  # قيمة افتراضية في حال عدم المزامنة بعد
    margin_level = 0.0

    if account:
        balance = float(account.balance or 1000.0)
        margin_level = float(account.margin_level or 0.0)
        
        # مكابح الطوارئ: إيقاف التداول فورا إذا اقترب الحساب من المارجن كول (< 300%)
        if margin_level > 0 and margin_level < 300:
            system_logger.critical(f"⚠️ تحذير خطير: مستوى الهامش منخفض جداً ({margin_level}%). تم حظر فتح صفقات جديدة!")
            return {"status": "ignored", "decision": "HOLD", "message": "Low margin safety block"}

    # حساب حجم العقد (Lot Size) بناءً على نسبة مخاطرة 1% من الرصيد
    risk_percentage = 0.01 
    base_lot = round((balance * risk_percentage) / 1000, 2)
    
    if symbol.upper() == "XAUUSD":
        lot_size = max(0.01, min(0.1, base_lot / 10))  # حماية إضافية للذهب
    else:
        lot_size = max(0.01, min(1.0, base_lot))       # لعملات الفوركس الرئيسية

    # حساب نقاط وقف الخسارة (SL) وجني الأرباح (TP) ديناميكياً
    pip_value = 0.01 if "JPY" in symbol.upper() else 0.0001
    if symbol.upper() == "XAUUSD":
        pip_value = 0.1

    current_price = float(market_data.get("close", 0.0))
    sl_price = 0.0
    tp_price = 0.0

    if current_price > 0:
        if decision == "BUY":
            sl_price = round(current_price - (20 * pip_value), 5)  # وقف خسارة 20 نقطة
            tp_price = round(current_price + (40 * pip_value), 5)  # جني أرباح 40 نقطة (عائد 1:2)
        elif decision == "SELL":
            sl_price = round(current_price + (20 * pip_value), 5)  # وقف خسارة 20 نقطة
            tp_price = round(current_price - (40 * pip_value), 5)  # جني أرباح 40 نقطة

    # ==========================================
    # 3. تجهيز وإرسال أمر التداول الآمن
    # ==========================================
    system_logger.info(f"🛡️ إدارة المخاطر لـ [{symbol}]: الرصيد={balance} | اللوت={lot_size} | الوقف={sl_price} | الهدف={tp_price}")

    new_command = schemas.CommandCreate(
        symbol=symbol,
        order_type=decision,
        lot_size=lot_size,
        stop_loss=sl_price,
        take_profit=tp_price
    )

    # 4. إرسال الأمر للاعتماد والحفظ في جدول trade_commands
    executed_command = trade_service.process_new_command(db=db, command=new_command)
    system_logger.info(f"✅ تم إنشاء أمر ذكي وآمن لـ [{symbol}] | النوع: {decision} | رقم الأمر: {executed_command.id}")

    return {
        "status": "success", 
        "decision": decision, 
        "symbol": symbol,
        "command_id": executed_command.id
    }
