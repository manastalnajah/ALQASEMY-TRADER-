import asyncio
from sqlalchemy import text

from database import SessionLocal

from app.indicators.moving_average import calculate_sma
from app.indicators.rsi import calculate_rsi
from app.services.strategy_service import evaluate_and_execute_strategy
from app.logging.logger import system_logger


# ============================================================
# ALQASEMY TRADER - MULTI-MARKET & MULTI-STRATEGY WORKER
# ============================================================
#
# مسؤولية هذا الملف:
# 1. دعم عدة أسواق نشطة (XAUUSD, EURUSD).
# 2. تشغيل عدة استراتيجيات بالتوازي (rsi, crossover, scalping).
# 3. زيادة فرص واقتناص الصفقات الحقيقية بأمان تام.
# ============================================================


SYMBOLS = ["XAUUSD", "EURUSD"]  # الأسواق المفعلة
STRATEGIES = ["rsi", "crossover", "scalping"]  # شبكة الاستراتيجيات المفعلة بالكامل
TIMEFRAME = "M5"

# نحتاج بيانات كافية لحساب مؤشر SMA(50)
CANDLE_LIMIT = 100

# الفاصل الزمني بين دورات الفحص الشامل
WORKER_INTERVAL_SECONDS = 5


async def analyze_symbol_with_strategies(db, symbol: str):
    """
    تحليق سوق معين باستخدام كافة الاستراتيجيات المتاحة
    """
    try:
        # 1. قراءة آخر الشموع الحقيقية لهذا الرمز من قاعدة البيانات
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

        # 2. التحقق من توفر بيانات كافية (50 شمعة على الأقل)
        if len(result) < 50:
            system_logger.info(
                f"⏳ بانتظار بيانات MT5 كافية لـ {symbol} {TIMEFRAME}: "
                f"{len(result)}/50 شمعة"
            )
            return

        # ترتيب الأسعار من الأقدم إلى الأحدث
        price_history = [
            float(row[0])
            for row in reversed(result)
            if row[0] is not None
        ]

        if len(price_history) < 50:
            return

        current_price = price_history[-1]

        if current_price <= 0:
            system_logger.warning(f"⚠️ سعر غير صالح لـ {symbol}: {current_price}")
            return

        # 3. حساب المؤشرات الفنية المشتركة لكل الاستراتيجيات
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

        # 4. تجهيز قاموس بيانات السوق الموحد
        market_data = {
            "symbol": symbol,
            "timeframe": TIMEFRAME,
            "price": current_price,
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "rsi": rsi_value,
        }

        system_logger.info(
            f"📊 [MULTI-STRATEGY M5] "
            f"{symbol} | "
            f"Price={current_price} | "
            f"MA10={fast_ma:.2f} | "
            f"MA50={slow_ma:.2f} | "
            f"RSI={rsi_value:.2f}"
        )

        # 5. المرور على جميع الاستراتيجيات وتقييم السوق عبرها تباعاً
        for strategy_name in STRATEGIES:
            # حماية لمنع تكدس الصفقات: فحص ما إذا كان هناك أمر معلق لنفس السوق حالياً
            check_pending = text("""
                SELECT count(*) FROM trade_commands 
                WHERE symbol = :symbol AND status = 'pending'
            """)
            count_pending = db.execute(check_pending, {"symbol": symbol}).scalar()

            if count_pending > 0:
                # إذا وجدنا أمراً معلقاً قيد التنفيذ، نتخطى الفحص المؤقت لمنع التزاحم
                break

            # تمرير البيانات إلى Strategy Manager عبر خدمة التنفيذ
            evaluate_and_execute_strategy(
                db=db,
                strategy_name=strategy_name,
                market_data=market_data,
            )

    except Exception as e:
        system_logger.error(
            f"❌ خطأ في تحليل السوق {symbol} بالاستراتيجيات المتعددة: {type(e).__name__}: {e}"
        )


async def run_trading_cycle():
    """
    تنفيذ دورة تحليل شاملة لكافة الأسواق والاستراتيجيات
    """
    db = SessionLocal()
    try:
        for symbol in SYMBOLS:
            await analyze_symbol_with_strategies(db, symbol)
    finally:
        db.close()


async def start_background_worker():
    """
    تشغيل محرك التداول متعدد الأسواق والاستراتيجيات في الخلفية
    """
    system_logger.info(
        "🚀 تشغيل ALQASEMY TRADER Multi-Strategy Live Trading Worker"
    )

    system_logger.info(
        f"📡 Symbols: {SYMBOLS} | "
        f"Strategies: {STRATEGIES} | "
        f"Interval: {WORKER_INTERVAL_SECONDS}s"
    )

    while True:
        try:
            await run_trading_cycle()

        except asyncio.CancelledError:
            system_logger.info("🛑 تم إيقاف Trading Worker.")
            raise

        except Exception as e:
            system_logger.error(
                f"❌ خطأ غير متوقع في Trading Worker: "
                f"{type(e).__name__}: {e}"
            )

        await asyncio.sleep(WORKER_INTERVAL_SECONDS)
