import asyncio
import random
# استدعاء ملف الاتصال لفتح الجلسات مع قاعدة البيانات
from database import SessionLocal
# استدعاء المؤشرات الرياضية
from app.indicators.moving_average import calculate_sma
from app.indicators.rsi import calculate_rsi
# استدعاء المدير التنفيذي
from app.services.strategy_service import evaluate_and_execute_strategy
from app.logging.logger import system_logger
from sqlalchemy import text  # 👈 أضفنا هذا الاستيراد لجلب الأسعار الحقيقية من جدول candles

async def run_trading_cycle():
    """
    هذه الدالة تمثل 'نبضة القلب' أو الدورة الواحدة للروبوت:
    جلب الأسعار الحقيقية -> حساب المؤشرات -> اتخاذ القرار -> التنفيذ
    """
    db = SessionLocal()
    try:
        # 1. جلب آخر الأسعار الحقيقية التي أرسلها ميتاتريدر وحفظناها في قاعدة البيانات
        query = text("""
            SELECT close FROM candles 
            WHERE symbol_name = 'EURUSD' AND timeframe = 'M5'
            ORDER BY open_time DESC 
            LIMIT 50
        """)
        result = db.execute(query).fetchall()
        
        # إذا لم تكن البيانات كافية بعد، ننتظر قليلاً
        if len(result) < 20:
            system_logger.info("⏳ بانتظار تجميع شمعات كافية من ميتاتريدر لحساب المؤشرات...")
            return

        # تحويل النتائج إلى قائمة أسعار مرتبة من الأقدم إلى الأحدث
        price_history = [row[0] for row in reversed(result)]
        current_price = price_history[-1]

        # 2. حساب المؤشرات الرياضية من الأسعار الحقيقية
        fast_ma = calculate_sma(price_history, period=10)
        slow_ma = calculate_sma(price_history, period=50)
        rsi_value = calculate_rsi(price_history, period=14)

        # 3. تجميع البيانات في قاموس واحد
        market_data = {
            "symbol": "EURUSD",
            "price": current_price,
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "rsi": rsi_value
        }

        system_logger.info(f"📊 [Live Strategy Analysis] EURUSD Price: {current_price} | RSI: {rsi_value}")

        # 4. تشغيل الاستراتيجية والإدارة التنفيذية الأصلية الخاصة بك
        evaluate_and_execute_strategy(
            db=db, 
            strategy_name="rsi", 
            market_data=market_data
        )
        
    except Exception as e:
        system_logger.error(f"❌ حدث خطأ أثناء تنفيذ الدورة: {str(e)}")
    finally:
        # إغلاق الاتصال فوراً للحفاظ على استقرار السيرفر (Supabase)
        db.close() 

async def start_background_worker():
    """
    محرك التشغيل المستمر (Loop): يعمل في الخلفية ولا يتوقف أبداً
    """
    system_logger.info("🚀 تشغيل محرك التداول الآلي في الخلفية (مرتبط ببيانات MT5 الحقيقية)...")
    while True:
        await run_trading_cycle()

        # الروبوت سينتظر لمدة 15 ثانية قبل تشغيل الدورة التالية
        await asyncio.sleep(15)
