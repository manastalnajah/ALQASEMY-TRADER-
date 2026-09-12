import asyncio
from sqlalchemy import text
from database import SessionLocal
from app.config import config
from app.indicators.moving_average import calculate_sma
from app.indicators.rsi import calculate_rsi
from app.indicators.atr import calculate_atr
from app.services.strategy_evaluator import evaluate_and_execute_strategy
from app.logging.logger import system_logger
from app.api.v1.bot_router import is_bot_running

# تم إضافة أوامر الـ STOP لتتطابق مع النظام
VALID_DECISIONS = {"BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}


def _load_candles(db, symbol: str, timeframe: str, limit: int):
    rows = db.execute(text("""
        SELECT open_time, open, high, low, close, volume
        FROM candles
        WHERE symbol_name=:symbol AND timeframe=:timeframe
        ORDER BY open_time DESC
        LIMIT :limit
    """), {"symbol": symbol, "timeframe": timeframe, "limit": limit}).mappings().all()
    return list(reversed(rows))


def _ma_context(candles, fast_period=10, slow_period=50):
    closes = [float(r["close"]) for r in candles]
    if len(closes) < slow_period + 1:
        return None
    fast = calculate_sma(closes, fast_period)
    slow = calculate_sma(closes, slow_period)
    if fast is None or slow is None:
        return None
    return {
        "fast_ma": float(fast),
        "slow_ma": float(slow),
        "close": float(closes[-1]),
        "bullish": float(fast) > float(slow) and float(closes[-1]) > float(slow),
        "bearish": float(fast) < float(slow) and float(closes[-1]) < float(slow),
    }


def analyze_symbol(db, symbol: str, active_accounts: list):
    """
    التعديل: تمرير قائمة الحسابات النشطة.
    يتم تقييم السوق (الشموع والمؤشرات) مرة واحدة توفيراً للموارد، 
    ثم يتم إرسال الإشارة لكل حساب ليتم تسعيرها بحجم اللوت الخاص به.
    """
    # Professional MTF pipeline:
    # H1 = market direction, M15 = confirmation, M5 = entry signal.
    direction_candles = _load_candles(db, symbol, config.direction_timeframe, config.direction_candle_limit)
    confirmation_candles = _load_candles(db, symbol, config.confirmation_timeframe, config.confirmation_candle_limit)
    entry_candles = _load_candles(db, symbol, config.entry_timeframe, config.entry_candle_limit)

    if (len(direction_candles) < config.min_candles_required or
            len(confirmation_candles) < config.min_candles_required or
            len(entry_candles) < config.min_candles_required):
        return

    direction = _ma_context(direction_candles)
    confirmation = _ma_context(confirmation_candles)
    if not direction or not confirmation:
        return

    # H1 and M15 must agree before M5 is allowed to generate an entry.
    if direction["bullish"] and confirmation["bullish"]:
        market_bias = "BUY"
    elif direction["bearish"] and confirmation["bearish"]:
        market_bias = "SELL"
    else:
        market_bias = "NEUTRAL"

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
    atr = calculate_atr(highs, lows, closes, config.atr_period)
    ma14 = calculate_sma(closes, 14)
    ma14_prev = calculate_sma(closes[:-1], 14)
    if None in (fast, slow, fast_prev, slow_prev, rsi, rsi_prev, atr, ma14, ma14_prev):
        return

    latest = entry_candles[-1]
    spec = db.execute(text("SELECT point, digits, tick_size, tick_value FROM symbol_specs WHERE symbol=:symbol"), {"symbol": symbol}).mappings().first()
    if not spec:
        system_logger.warning("🛑 %s: symbol specification missing; trading blocked", symbol)
        return

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
        "fast_ma": float(fast),
        "slow_ma": float(slow),
        "fast_ma_prev": float(fast_prev),
        "slow_ma_prev": float(slow_prev),
        "rsi": float(rsi),
        "rsi_prev": float(rsi_prev),
        "atr": float(atr),
        "ma_14": float(ma14),
        "ma_14_prev": float(ma14_prev),
        "point": float(spec["point"]),
    }

    # تطبيق الإستراتيجيات لكل حساب نشط
    for account in active_accounts:
        market_for_account = market.copy()
        # حقن معرف الـ EA الخاص بالحساب
        market_for_account["ea_id"] = str(account["ea_id"] or "")
        account_id = str(account["id"])
        
        for strategy_name in config.enabled_strategies:
            # تمرير account_id بشكل إلزامي
            result = evaluate_and_execute_strategy(db, account_id, strategy_name, market_for_account)
            
            if result.get("decision") in VALID_DECISIONS:
                system_logger.info("🎯 Account %s | MTF %s H1=%s M15=%s M5=%s -> %s %s", 
                                   account["account_number"], symbol, market_bias, 
                                   confirmation["bullish"] and "BUY" or confirmation["bearish"] and "SELL" or "NEUTRAL", 
                                   config.entry_timeframe, strategy_name, result)
                break  # إذا نجحت استراتيجية، ننتقل للرمز/الحساب التالي ولا نُكمل باقي الاستراتيجيات لنفس الرمز


def run_cycle_sync():
    db = SessionLocal()
    try:
        if not is_bot_running(db):
            return
        
        # One DB advisory lock protects against two API instances running workers simultaneously.
        acquired = db.execute(text("SELECT pg_try_advisory_lock(hashtext('ALQASEMY:TRADING_WORKER'))")).scalar()
        if not acquired:
            return
            
        try:
            # جلب الحسابات النشطة والمتصلة حالياً
            active_accounts = db.execute(text("""
                SELECT id, account_number, ea_id 
                FROM trading_accounts 
                WHERE is_connected = true
            """)).mappings().all()
            
            if not active_accounts:
                return  # لا يوجد حسابات نشطة، لا داعي لإرهاق السيرفر بتحليل الشموع
                
            for symbol in config.symbols:
                analyze_symbol(db, symbol, active_accounts)
                
            db.commit()
        finally:
            db.execute(text("SELECT pg_advisory_unlock(hashtext('ALQASEMY:TRADING_WORKER'))"))
            
    except Exception as exc:
        db.rollback()
        system_logger.exception("Trading cycle failed: %s", exc)
    finally:
        db.close()


async def start_background_worker():
    system_logger.info("🚀 ALQASEMY hardened trading worker started | symbols=%s | H1=%s | M15=%s | Entry=%s", 
                       config.symbols, config.direction_timeframe, config.confirmation_timeframe, config.entry_timeframe)
    while True:
        try:
            await asyncio.to_thread(run_cycle_sync)
        except asyncio.CancelledError:
            system_logger.info("🛑 Trading worker stopped")
            raise
        except Exception as exc:
            system_logger.exception("Worker loop failure: %s", exc)
            
        await asyncio.sleep(max(1, config.worker_interval_seconds))
