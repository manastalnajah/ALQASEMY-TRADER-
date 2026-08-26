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

# (للتجربة فقط) محاكاة وهمية لأسعار السوق السابقة 
# في النظام الحقيقي، سيتم قراءة هذه الأسعار من منصة الميتاتريدر أو واجهة API خارجية
price_history = [1.0500 + (random.uniform(-0.0010, 0.0010)) for _ in range(100)]

async def run_trading_cycle():
    """
    هذه الدالة تمثل 'نبضة القلب' أو الدورة الواحدة للروبوت:
    جلب الأسعار -> حساب المؤشرات -> اتخاذ القرار -> التنفيذ
    """
    # 1. تحديث الأسعار (إضافة سعر الشمعة الجديدة)
    current_price = price_history[-1] + random.uniform(-0.0005, 0.0005)
    price_history.append(current_price)
    
    # 2. حساب المؤشرات الرياضية من الأسعار الحالية
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
    
    # 4. فتح جلسة اتصال سريعة بقاعدة البيانات
    db = SessionLocal()
    try:
        # 5. تشغيل الاستراتيجية!
        # هنا نخبر النظام: "استخدم استراتيجية RSI بناءً على أسعار السوق الحالية"
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
    system_logger.info("🚀 تشغيل محرك التداول الآلي في الخلفية...")
    while True:
        await run_trading_cycle()
        
        # الروبوت سينتظر لمدة 60 ثانية (دقيقة) قبل قراءة الشمعة التالية
        # يمكنك تغييرها إلى 5 ثوانٍ للسكالبينج السريع جداً
        await asyncio.sleep(60)