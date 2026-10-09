# ============================================================
# app/workers/trading_worker.py
# النسخة: 2.2.0
# ------------------------------------------------------------
# التغييرات عن 2.1.0:
# - ✅ إصلاح حرج: تمرير balance, equity, tick_size, tick_value
#   إلى market_data (كانت مفقودة → "Balance not found")
# - ✅ تحديث استعلام active_accounts لجلب balance و equity
# ============================================================

import asyncio

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from app.config import config
from app.indicators.moving_average import calculate_sma
from app.indicators.rsi import calculate_rsi
from app.indicators.atr import calculate_atr
from app.services.strategy_evaluator import evaluate_and_execute_strategy
from app.logging.logger import system_logger
from app.api.v1.bot_router import is_bot_running


# أنواع القرارات المقبولة (بما فيها أوامر STOP)
VALID_DECISIONS = {
    "BUY", "SELL",
    "BUY_LIMIT", "SELL_LIMIT",
    "BUY_STOP", "SELL_STOP",
}

# مفتاح advisory lock لمنع تشغيل دورتين متزامنتين
WORKER_LOCK_KEY = "ALQASEMY:TRADING_WORKER"


def _get_last_val(data) -> float:
    """
    🛡️ دالة دفاعية لاستخراج القيمة الأخيرة من أي نوع بيانات
    (Pandas Series, List, Float)
    """
    if data is None:
        return 0.0
    if hasattr(data, "iloc"):
        val = data.iloc[-1]
        return float(val)
    if isinstance(data, (list, tuple)) and len(data) > 0:
        return float(data[-1])
    return float(data)


async def _load_candles(
    db: AsyncSession,
    symbol: str,
    timeframe: str,
    limit: int,
):
    """تحميل آخر N شمعة من قاعدة البيانات."""
    rows = (await db.execute(text("""
        SELECT open_time, open, high, low, close, volume
        FROM candles
        WHERE symbol_name = :symbol
          AND timeframe = :timeframe
        ORDER BY open_time DESC
        LIMIT :limit
    """), {
        "symbol": symbol,
        "timeframe": timeframe,
        "limit": limit,
    })).mappings().all()
    return list(reversed(rows))


def _ma_context(
    candles,
    fast_period: int = 10,
    slow_period: int = 50,
):
    """سياق المتوسطات المتحركة على إطار زمني واحد."""
    closes = [float(r["close"]) for r in candles]
    if len(closes) < slow_period + 1:
        return None

    fast = calculate_sma(closes, fast_period)
    slow = calculate_sma(closes, slow_period)

    if fast is None or slow is None:
        return None

    fast_val = _get_last_val(fast)
    slow_val = _get_last_val(slow)
    close_val = float(closes[-1])

    return {
        "fast_ma": fast_val,
        "slow_ma": slow_val,
        "close": close_val,
        "bullish": fast_val > slow_val and close_val > slow_val,
        "bearish": fast_val < slow_val and close_val < slow_val,
    }


async def analyze_symbol(
    db: AsyncSession,
    symbol: str,
    active_accounts: list,
):
    """
    تحليل رمز واحد وإرسال الإشارة لكل حساب نشط.

    - يتم تقييم السوق (الشموع والمؤشرات) مرة واحدة.
    - لكل حساب، تُحسب اللوت بحسب رصيده.
    """
    # --------------------------------------------------------
    # 1. تحميل الشموع لثلاثة أطر زمنية
    # --------------------------------------------------------
    direction_candles = await _load_candles(
        db, symbol,
        config.direction_timeframe,
        config.direction_candle_limit,
    )
    confirmation_candles = await _load_candles(
        db, symbol,
        config.confirmation_timeframe,
        config.confirmation_candle_limit,
    )
    entry_candles = await _load_candles(
        db, symbol,
        config.entry_timeframe,
        config.entry_candle_limit,
    )

    if (
        len(direction_candles) < config.min_candles_required
        or len(confirmation_candles) < config.min_candles_required
        or len(entry_candles) < config.min_candles_required
    ):
        return

    # --------------------------------------------------------
    # 2. سياق الاتجاه (Direction + Confirmation)
    # --------------------------------------------------------
    direction = _ma_context(direction_candles)
    confirmation = _ma_context(confirmation_candles)

    if not direction or not confirmation:
        return

    if direction["bullish"] and confirmation["bullish"]:
        market_bias = "BUY"
    elif direction["bearish"] and confirmation["bearish"]:
        market_bias = "SELL"
    else:
        market_bias = "NEUTRAL"

    # --------------------------------------------------------
    # 3. مؤشرات الدخول
    # --------------------------------------------------------
    closes = [float(r["close"]) for r in entry_candles]
    highs = [float(r["high"]) for r in entry_candles]
    lows = [float(r["low"]) for r in entry_candles]

    if any(v <= 0 for v in closes):
        return

    fast = calculate_sma(closes, 10)
    slow = calculate_sma(closes, 50)
    fast_prev = calculate_sma(closes[:-1], 10)
    slow_prev = calculate_sma(closes[:-1], 50)

    rsi = calculate_rsi(closes, 14)
    rsi_prev = calculate_rsi(closes[:-1], 14)

    # ATR يحتاج DataFrame
    df_for_atr = pd.DataFrame({
        "high": highs,
        "low": lows,
        "close": closes,
    })
    atr = calculate_atr(df_for_atr, config.atr_period)

    ma14 = calculate_sma(closes, 14)
    ma14_prev = calculate_sma(closes[:-1], 14)

    if (
        fast is None
        or slow is None
        or rsi is None
        or atr is None
        or ma14 is None
    ):
        return

    latest = entry_candles[-1]

    # --------------------------------------------------------
    # 4. مواصفات الرمز
    # --------------------------------------------------------
    spec = (await db.execute(text("""
        SELECT point, digits, tick_size, tick_value
        FROM symbol_specs
        WHERE symbol = :symbol
    """), {"symbol": symbol})).mappings().first()

    if not spec:
        system_logger.warning(
            "🛑 %s: symbol specification missing; trading blocked",
            symbol,
        )
        return

    # استخراج مسبق لقيم المواصفات (تُستخدم لكل حساب)
    tick_size_val = float(spec["tick_size"] or 0.0)
    tick_value_val = float(spec["tick_value"] or 0.0)

    # --------------------------------------------------------
    # 5. بناء market_data
    # --------------------------------------------------------
    market = {
        "symbol": symbol,
        "timeframe": config.entry_timeframe,
        "direction_timeframe": config.direction_timeframe,
        "confirmation_timeframe": config.confirmation_timeframe,
        "entry_timeframe": config.entry_timeframe,
        "market_bias": market_bias,
        "h1_bullish": direction["bullish"] if config.direction_timeframe == "H1" else None,
        "h1_bearish": direction["bearish"] if config.direction_timeframe == "H1" else None,
        "higher_tf_bullish": direction["bullish"],
        "higher_tf_bearish": direction["bearish"],
        "confirmation_bullish": confirmation["bullish"],
        "confirmation_bearish": confirmation["bearish"],
        "direction_close": direction["close"],
        "confirmation_close": confirmation["close"],
        "open_time": str(latest["open_time"]),
        "candle_key": str(latest["open_time"]),
        "open": float(latest["open"]),
        "high": float(latest["high"]),
        "low": float(latest["low"]),
        "close": float(latest["close"]),
        "price": float(latest["close"]),
        "fast_ma": _get_last_val(fast),
        "slow_ma": _get_last_val(slow),
        "fast_ma_prev": _get_last_val(fast_prev),
        "slow_ma_prev": _get_last_val(slow_prev),
        "rsi": _get_last_val(rsi),
        "rsi_prev": _get_last_val(rsi_prev),
        "atr": _get_last_val(atr),
        "ma_14": _get_last_val(ma14),
        "ma_14_prev": _get_last_val(ma14_prev),
        "point": float(spec["point"]),
        # ✅ مواصفات الرمز (مشتركة بين الحسابات)
        "tick_size": tick_size_val,
        "tick_value": tick_value_val,
    }

    # --------------------------------------------------------
    # 6. لكل حساب نشط
    # --------------------------------------------------------
    for account in active_accounts:
        market_for_account = market.copy()
        market_for_account["ea_id"] = str(account["ea_id"] or "")
        market_for_account["account_number"] = int(account["account_number"])

        # ✅ جديد: رأس المال لكل حساب
        market_for_account["balance"] = float(account.get("balance") or 0.0)
        market_for_account["equity"] = float(account.get("equity") or 0.0)
        market_for_account["currency"] = str(account.get("currency") or "USD")

        account_id = str(account["id"])

        for strategy_name in config.enabled_strategies:
            result = await evaluate_and_execute_strategy(
                db,
                account_id,
                strategy_name,
                market_for_account,
            )

            if result.get("decision") in VALID_DECISIONS:
                system_logger.info(
                    "🎯 Account %s | MTF %s H1=%s M15=%s M5=%s -> %s %s",
                    account["account_number"],
                    symbol,
                    market_bias,
                    confirmation["bullish"] and "BUY" or (
                        confirmation["bearish"] and "SELL" or "NEUTRAL"
                    ),
                    config.entry_timeframe,
                    strategy_name,
                    result,
                )
                break


async def run_cycle():
    """
    دورة واحدة من التداول:
    1. التحقق من حالة البوت.
    2. الحصول على advisory lock.
    3. جلب الحسابات النشطة.
    4. تحليل كل رمز.
    5. تحرير القفل.
    """
    async with AsyncSessionLocal() as db:
        lock_acquired = False
        try:
            # --------------------------------------------------
            # 1. التحقق من حالة البوت
            # --------------------------------------------------
            bot_running = await is_bot_running(db)
            if not bot_running:
                return

            # --------------------------------------------------
            # 2. advisory lock
            # --------------------------------------------------
            acquired = (await db.execute(text(
                "SELECT pg_try_advisory_lock(hashtext(:key))"
            ), {"key": WORKER_LOCK_KEY})).scalar()

            if not acquired:
                return

            lock_acquired = True

            # --------------------------------------------------
            # 3. جلب الحسابات النشطة
            # ✅ جلب balance و equity و currency
            # --------------------------------------------------
            active_accounts = (await db.execute(text("""
                SELECT id, account_number, ea_id, balance, equity, currency
                FROM trading_accounts
                WHERE is_connected = true
                  AND is_active = true
                  AND is_trade_allowed = true
            """))).mappings().all()

            if not active_accounts:
                return

            # --------------------------------------------------
            # 4. تحليل الرموز
            # --------------------------------------------------
            for symbol in config.symbols:
                try:
                    await analyze_symbol(db, symbol, active_accounts)
                except Exception as sym_exc:
                    system_logger.exception(
                        "Symbol analysis failed for %s: %s",
                        symbol, sym_exc,
                    )

            await db.commit()

        except Exception as exc:
            await db.rollback()
            system_logger.exception("Trading cycle failed: %s", exc)

        finally:
            # --------------------------------------------------
            # 5. تحرير advisory lock
            # --------------------------------------------------
            if lock_acquired:
                try:
                    await db.execute(text(
                        "SELECT pg_advisory_unlock(hashtext(:key))"
                    ), {"key": WORKER_LOCK_KEY})
                    await db.commit()
                except Exception as unlock_exc:
                    system_logger.warning(
                        "Failed to release advisory lock: %s",
                        unlock_exc,
                    )


async def start_background_worker():
    """
    حلقة لا نهائية تشغّل run_cycle كل N ثانية.
    """
    system_logger.info(
        "🚀 ALQASEMY hardened trading worker started | "
        "symbols=%s | H1=%s | M15=%s | Entry=%s",
        config.symbols,
        config.direction_timeframe,
        config.confirmation_timeframe,
        config.entry_timeframe,
    )

    while True:
        try:
            await run_cycle()
        except asyncio.CancelledError:
            system_logger.info("🛑 Trading worker stopped")
            raise
        except Exception as exc:
            system_logger.exception("Worker loop failure: %s", exc)

        await asyncio.sleep(max(1, config.worker_interval_seconds))
