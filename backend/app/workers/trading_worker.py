import asyncio
from datetime import datetime, timedelta
from sqlalchemy import text

from database import SessionLocal

from app.indicators.moving_average import calculate_sma
from app.indicators.rsi import calculate_rsi
from app.services.strategy_service import evaluate_and_execute_strategy
from app.logging.logger import system_logger

# ⚠️ التعديل الجديد: استدعاء حالة البوت من ملف الـ API الذي قمت بإنشائه
# (يرجى التأكد من مسار الاستيراد حسب اسم المجلد والملف لديك، مثلاً app.api.bot_control)
from app.api.bot_control import bot_state 


# ============================================================
# ALQASEMY TRADER - SECURE MULTI-STRATEGY WORKER (WITH COOLDOWN)
# ============================================================

SYMBOLS = ["XAUUSD", "EURUSD"]
STRATEGIES = ["rsi", "crossover", "scalping"]
TIMEFRAME = "M5"

CANDLE_LIMIT = 100
WORKER_INTERVAL_SECONDS = 5

# تخزين وقت آخر صفقة تم إرسالها لكل سوق لمنع التكرار الجنوني
last_trade_times = {}
COOLDOWN_MINUTES = 3  # فترة تبريد 3 دقائق بين كل صفقة وأخرى لنفس السوق


async def analyze_symbol_with_strategies(db, symbol: str):
    try:
        # 1. التحقق من فترة التبريد (Cooldown) لمنع إغراق السوق بصفقات مكررة
        global last_trade_times
        if symbol in last_trade_times:
            elapsed = datetime.utcnow() - last_trade_times[symbol]
            if elapsed < timedelta(minutes=COOLDOWN_MINUTES):
                # لا زال السوق في فترة التبريد، نتخطى التحليل مؤقتاً
                return

        # 2. قراءة آخر الشموع الحقيقية
        query = text("""
            SELECT close
            FROM candles
            WHERE symbol_name = :symbol
              AND timeframe = :timeframe
              AND close IS NOT NULL
            ORDER BY open_time DESC
            LIMIT :limit
        """)

        result = db.execute(
            query,
            {
                "symbol": symbol,
                "timeframe": TIMEFRAME,
                "limit": CANDLE_LIMIT,
            },
        ).fetchall()

        if len(result) < 50:
            return

        price_history = [
            float(row[0])
            for row in reversed(result)
            if row[0] is not None
        ]

        if len(price_history) < 50:
            return

        current_price = price_history[-1]

        if current_price <= 0:
            return

        # 3. حساب المؤشرات الفنية
        fast_ma = calculate_sma(price_history, period=10)
        slow_ma = calculate_sma(price_history, period=50)
        rsi_value = calculate_rsi(price_history, period=14)

        if fast_ma is None or slow_ma is None or rsi_value is None:
            return

        try:
            fast_ma = float(fast_ma)
            slow_ma = float(slow_ma)
            rsi_value = float(rsi_value)
        except (TypeError, ValueError):
            return

        market_data = {
            "symbol": symbol,
            "timeframe": TIMEFRAME,
            "price": current_price,
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "rsi": rsi_value,
        }

        system_logger.info(
            f"📊 [SECURE M5] "
            f"{symbol} | "
            f"Price={current_price} | "
            f"MA10={fast_ma:.2f} | "
            f"MA50={slow_ma:.2f} | "
            f"RSI={rsi_value:.2f}"
        )

        # 4. فحص الأوامر المعلقة أو قيد المعالجة في قاعدة البيانات
        check_active = text("""
            SELECT count(*) FROM trade_commands 
            WHERE symbol = :symbol AND status IN ('pending', 'processing')
        """)
        count_active = db.execute(check_active, {"symbol": symbol}).scalar()

        if count_active > 0:
            system_logger.info(f"⏳ يوجد أمر سابق قيد التنفيذ لـ {symbol}، جاري الانتظار...")
            return

        # 5. المرور على الاستراتيجيات وتقييم السوق
        for strategy_name in STRATEGIES:
            # تقييم الاستراتيجية
            # (نكتفي بأول استراتيجية تعطي إشارة صالحة في هذه الدورة لتجنب تضارب الصفقات)
            result_decision = evaluate_and_execute_strategy(
                db=db,
                strategy_name=strategy_name,
                market_data=market_data,
            )

            # إذا قامت الاستراتيجية بإصدار أمر حقيقي، نسجل وقت التبريد ونخرج من حلقة الاستراتيجيات
            if result_decision and result_decision.get("decision") in ["BUY", "SELL"]:
                last_trade_times[symbol] = datetime.utcnow()
                break

    except Exception as e:
        system_logger.error(
            f"❌ خطأ في تحليل السوق {symbol}: {type(e).__name__}: {e}"
        )


async def run_trading_cycle():
    # 💡 التعديل الأهم: التحقق من حالة البوت قبل فتح قاعدة البيانات أو إرهاق السيرفر
    if not bot_state.get("is_running", False):
        return  # البوت مطفأ من التطبيق، انسحاب هادئ دون فعل أي شيء

    db = SessionLocal()
    try:
        for symbol in SYMBOLS:
            await analyze_symbol_with_strategies(db, symbol)
    finally:
        db.close()


async def start_background_worker():
    system_logger.info(
        "🚀 تشغيل محرك التداول الآمن والمحمى (Secure Multi-Strategy Worker)"
    )
    system_logger.info(
        f"📡 Symbols: {SYMBOLS} | Strategies: {STRATEGIES} | Cooldown: {COOLDOWN_MINUTES}m"
    )

    while True:
        try:
            await run_trading_cycle()
        except asyncio.CancelledError:
            system_logger.info("🛑 تم إيقاف Trading Worker.")
            raise
        except Exception as e:
            system_logger.error(
                f"❌ خطأ غير متوقع في Trading Worker: {type(e).__name__}: {e}"
            )

        await asyncio.sleep(WORKER_INTERVAL_SECONDS)
