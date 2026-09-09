import asyncio
from sqlalchemy import text

from database import SessionLocal

from app.indicators.moving_average import calculate_sma
from app.indicators.rsi import calculate_rsi
from app.services.strategy_service import evaluate_and_execute_strategy
from app.logging.logger import system_logger


# ============================================================
# ALQASEMY TRADER - LIVE TRADING WORKER
# ============================================================
#
# مسؤولية هذا الملف:
# 1. قراءة بيانات السوق الحقيقية القادمة من MT5.
# 2. حساب المؤشرات.
# 3. إرسال بيانات السوق إلى Strategy Service.
#
# هذا الملف لا يحتوي على:
# - BUY إجباري
# - SELL إجباري
# - فتح صفقات مباشرة
# - إغلاق صفقات مباشرة
# - أسعار عشوائية
#
# قرار التداول وتنفيذ الأمر يتمان في الطبقات المخصصة لذلك.
# ============================================================


SYMBOL = "EURUSD"
TIMEFRAME = "M5"

# نحتاج بيانات أكثر من فترة SMA(50)
# حتى لا تبدأ الاستراتيجية ببيانات غير كافية.
CANDLE_LIMIT = 100

# الفاصل بين دورات التحليل.
# بما أن البيانات M5، لا توجد حاجة لفحص الاستراتيجية كل ثانيتين.
WORKER_INTERVAL_SECONDS = 5


async def run_trading_cycle():
    """
    تنفيذ دورة تحليل واحدة اعتمادًا على بيانات MT5 الحقيقية.

    لا يتم إنشاء أي أمر تداول إجباري هنا.
    """

    db = SessionLocal()

    try:
        # =====================================================
        # 1. قراءة آخر شموع EURUSD / M5 من قاعدة البيانات
        # =====================================================

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
                "symbol": SYMBOL,
                "timeframe": TIMEFRAME,
                "limit": CANDLE_LIMIT,
            },
        ).fetchall()

        # =====================================================
        # 2. التحقق من توفر بيانات كافية
        # =====================================================

        if len(result) < 50:
            system_logger.info(
                f"⏳ بانتظار بيانات MT5 كافية لـ {SYMBOL} {TIMEFRAME}: "
                f"{len(result)}/50 شمعة"
            )
            return

        # قاعدة البيانات ترجع الأحدث أولًا.
        # نقلب القائمة حتى تصبح من الأقدم إلى الأحدث.
        price_history = [
            float(row[0])
            for row in reversed(result)
            if row[0] is not None
        ]

        if len(price_history) < 50:
            system_logger.info(
                f"⏳ بيانات الأسعار غير كافية بعد: "
                f"{len(price_history)}/50"
            )
            return

        current_price = price_history[-1]

        if current_price <= 0:
            system_logger.warning(
                f"⚠️ سعر غير صالح من MT5: {current_price}"
            )
            return

        # =====================================================
        # 3. حساب المؤشرات
        # =====================================================

        fast_ma = calculate_sma(
            price_history,
            period=10,
        )

        slow_ma = calculate_sma(
            price_history,
            period=50,
        )

        rsi_value = calculate_rsi(
            price_history,
            period=14,
        )

        # =====================================================
        # 4. التحقق من نتائج المؤشرات
        # =====================================================

        if fast_ma is None or slow_ma is None or rsi_value is None:
            system_logger.warning(
                "⚠️ لم يتم الحصول على نتائج صالحة للمؤشرات."
            )
            return

        # بعض دوال المؤشرات قد تعيد قيمة رقمية غير صالحة.
        try:
            fast_ma = float(fast_ma)
            slow_ma = float(slow_ma)
            rsi_value = float(rsi_value)
        except (TypeError, ValueError):
            system_logger.warning(
                "⚠️ تعذر تحويل نتائج المؤشرات إلى أرقام."
            )
            return

        # =====================================================
        # 5. تجهيز بيانات السوق للاستراتيجية
        # =====================================================

        market_data = {
            "symbol": SYMBOL,
            "timeframe": TIMEFRAME,
            "price": current_price,
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "rsi": rsi_value,
        }

        system_logger.info(
            f"📊 [LIVE M5] "
            f"{SYMBOL} | "
            f"Price={current_price} | "
            f"SMA10={fast_ma:.5f} | "
            f"SMA50={slow_ma:.5f} | "
            f"RSI={rsi_value:.2f}"
        )

        # =====================================================
        # 6. تمرير البيانات إلى Strategy Service
        # =====================================================
        #
        # مهم جدًا:
        # هذا الملف لا ينشئ BUY أو SELL بنفسه.
        #
        # إذا كانت الاستراتيجية تقرر:
        # BUY  -> service ينشئ الأمر
        # SELL -> service ينشئ الأمر
        # HOLD -> لا يوجد أمر
        # CLOSE -> يجب أن تتعامل معه طبقة إدارة الصفقات
        #
        # لذلك لا نضع أي INSERT مباشر إلى trade_commands هنا.
        # =====================================================

        evaluate_and_execute_strategy(
            db=db,
            strategy_name="rsi",
            market_data=market_data,
        )

    except Exception as e:
        system_logger.error(
            f"❌ خطأ في دورة التداول: "
            f"{type(e).__name__}: {e}"
        )

    finally:
        db.close()


async def start_background_worker():
    """
    تشغيل محرك التحليل في الخلفية.

    يعمل باستمرار على بيانات MT5 الحقيقية.
    """

    system_logger.info(
        "🚀 تشغيل ALQASEMY TRADER Live Trading Worker"
    )

    system_logger.info(
        f"📡 Symbol: {SYMBOL} | "
        f"Timeframe: {TIMEFRAME} | "
        f"Interval: {WORKER_INTERVAL_SECONDS}s"
    )

    system_logger.info(
        "🛑 لا توجد أوامر BUY/SELL إجبارية في هذا العامل."
    )

    while True:
        try:
            await run_trading_cycle()

        except asyncio.CancelledError:
            system_logger.info(
                "🛑 تم إيقاف Trading Worker."
            )
            raise

        except Exception as e:
            system_logger.error(
                f"❌ خطأ غير متوقع في Trading Worker: "
                f"{type(e).__name__}: {e}"
            )

        await asyncio.sleep(WORKER_INTERVAL_SECONDS)
