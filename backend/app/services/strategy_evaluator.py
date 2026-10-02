from sqlalchemy.ext.asyncio import AsyncSession  # 🛠️ تم التحديث لدعم Async
from sqlalchemy import text
from app.strategies.strategy_manager import manager as strategy_manager
from app.services import trade_service
from app.domain import schemas
from app.logging.logger import system_logger
from app.config import config
from datetime import datetime, timezone

# 🚀 استدعاء المحرك الرياضي الجديد للعمل كدرع حماية
from app.services.quant_analyzer import QuantAnalyzer

quant_analyzer = QuantAnalyzer()


def _safe_float(val, default: float = 0.0) -> float:
    if val is None:
        return default
    if hasattr(val, "iloc"):
        val = val.iloc[-1]
    elif isinstance(val, (list, tuple)) and len(val) > 0:
        val = val[-1]
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _price(market_data: dict, decision: str) -> float:
    """قراءة السعر النهائي بدقة تامة لتعويض السبريد بناءً على نوع الصفقة"""
    if decision.startswith("BUY"):
        return _safe_float(market_data.get("ask") or market_data.get("close") or 0.0)
    elif decision.startswith("SELL"):
        return _safe_float(market_data.get("bid") or market_data.get("close") or 0.0)
    return _safe_float(market_data.get("close", 0.0))


def _build_protection(market_data: dict, decision: str, entry: float, sl: float, tp: float):
    """بناء مستويات الوقف والهدف بدقة مع قيم احتياطية آمنة في حال تأخر مؤشر ATR"""
    if sl > 0 and tp > 0:
        return sl, tp

    atr = _safe_float(market_data.get("atr"), 0.0)
    symbol = str(market_data.get("symbol", "")).upper()

    if atr <= 0:
        # قيمة افتراضية آمنة للوقف في حال عدم توفر ATR لحظياً (30 نقطة لليورو و 2.0 دولار للذهب)
        atr = 2.0 if "XAU" in symbol else 0.0030

    risk_distance = atr * getattr(config, "atr_sl_multiplier", 1.5)
    rr = getattr(config, "reward_risk", 1.5)

    if decision.startswith("BUY"):
        return round(entry - risk_distance, 5), round(entry + (risk_distance * rr), 5)
    if decision.startswith("SELL"):
        return round(entry + risk_distance, 5), round(entry - (risk_distance * rr), 5)
    return 0.0, 0.0


def _calculate_dynamic_lot(symbol: str, entry: float, sl: float, market_data: dict) -> float:
    """الحساب النهائي للوت مع الحماية ضد انعدام الرصيد أو انهيار الاتصال"""
    balance_raw = market_data.get("balance") or market_data.get("equity")
    if balance_raw is None:
        system_logger.error(f"🛑 CRITICAL: Balance not found for {symbol}. Blocking execution.")
        return 0.0  # إيقاف التنفيذ لحماية الحساب

    balance = _safe_float(balance_raw)
    if balance <= 0:
        return 0.0

    risk_pct = getattr(config, "risk_per_trade_pct", 1.0)
    risk_amount = balance * (risk_pct / 100.0)
    sl_distance = abs(entry - sl)

    if sl_distance <= 0:
        return 0.01

    tick_size = _safe_float(market_data.get("tick_size"), 0.0)
    tick_value = _safe_float(market_data.get("tick_value"), 0.0)

    if tick_size > 0 and tick_value > 0:
        ticks_at_risk = sl_distance / tick_size
        lot_size = risk_amount / (ticks_at_risk * tick_value)
    else:
        # معادلات الطوارئ المحسنة
        lot_size = risk_amount / (sl_distance * (100 if "XAU" in symbol else 1000 if "JPY" in symbol else 100000))

    lot_size = round(lot_size, 2)
    max_lots = getattr(config, "max_symbol_exposure_lots", 5.0)
    return max(0.01, min(lot_size, max_lots))


# محرك رياضي داخلي لحساب RSI من قاعدة البيانات لضمان دقة الإشارات
def calculate_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# 🛠️ الدالة الرئيسية لتنفيذ وتقييم الاستراتيجيات مع الدرع الرياضي
async def evaluate_and_execute_strategy(db: AsyncSession, account_id: str, strategy_name: str, market_data: dict):
    symbol = str(market_data.get("symbol") or "").upper()
    timeframe = str(market_data.get("timeframe") or getattr(config, "timeframe", "M5")).upper()
    candle_key = str(market_data.get("candle_key") or market_data.get("open_time") or "")

    if not symbol or not candle_key:
        return {"status": "ignored", "decision": "HOLD", "message": "Missing identity"}

    # ==================================================
    # 🛡️ فلتر أوقات الجلسات العالمية الفعالة
    # ==================================================
    current_utc_hour = datetime.now(timezone.utc).hour
    if not (7 <= current_utc_hour <= 21):
        system_logger.info(f"⏳ HOLD: {symbol} is outside active session hours (Current UTC: {current_utc_hour}).")
        return {"status": "ignored", "decision": "HOLD", "message": "Outside active market sessions"}

    current_volume = _safe_float(market_data.get("volume"), 0.0)
    
    # ==================================================
    # 🚀 تجهيز البيانات الشاملة
    # ==================================================
    try:
        rows = (await db.execute(text("""
            SELECT open_time, open, high, low, close, volume 
            FROM candles 
            WHERE symbol_name = :sym AND timeframe = :tf 
            ORDER BY open_time DESC LIMIT 150
        """), {"sym": symbol, "tf": timeframe})).mappings().all()

        candles_list = [dict(r) for r in rows][::-1]
        market_data["candles"] = candles_list

        if len(candles_list) >= 40:
            recent_40 = candles_list[-40:]
            market_data["support"] = min(float(c["low"]) for c in recent_40)
            market_data["resistance"] = max(float(c["high"]) for c in recent_40)
        else:
            market_data["support"] = float(market_data.get("low", 0.0))
            market_data["resistance"] = float(market_data.get("high", 0.0))
        
        market_data["point"] = _safe_float(market_data.get("tick_size"), 0.00001)

    except Exception as e:
        system_logger.error(f"❌ Error preparing historical data for {symbol}: {e}")
        return {"status": "error", "decision": "HOLD", "message": "Data preparation failed"}

    # ==================================================
    # 🧮 تجهيز الدرع الرياضي (Quant Shield) للبيانات الحالية
    # ==================================================
    close_prices = [float(c["close"]) for c in candles_list]
    quant_report = quant_analyzer.analyze_single_asset(close_prices)

    try:
        # ==================================================
        # 🧠 حلقة العقول المدبرة (Multi-Strategy Engine)
        # ==================================================
        active_strategies = ["rsi_reversion", "golden_setup", "smart_limits"]
        
        final_decision = "HOLD"
        final_result = {}
        executed_strategy = ""

        for strat in active_strategies:
            decision = "HOLD"
            result = {}

            if strat == "smart_limits" and not getattr(config, "allow_smart_limits", True):
                continue
            if strat == "golden_setup" and not getattr(config, "allow_golden_setup", True):
                continue

            if strat == "rsi_reversion":
                if len(rows) >= 15:
                    prices = [float(r["close"]) for r in rows][::-1]
                    rsi_value = calculate_rsi(prices, period=14)
                    oversold = getattr(config, "rsi_oversold_level", 30.0)
                    overbought = getattr(config, "rsi_overbought_level", 70.0)
                    
                    if 0 < rsi_value <= oversold:
                        decision = "BUY"
                    elif rsi_value >= overbought:
                        decision = "SELL"
            else:
                result = strategy_manager.execute(strat, market_data)
                decision = str(result.get("decision", "HOLD")).upper() if isinstance(result, dict) else str(result).upper()

            if decision != "HOLD":
                final_decision = decision
                final_result = result if isinstance(result, dict) else {}
                executed_strategy = strat
                break

        if final_decision == "HOLD":
            return {"status": "success", "decision": "HOLD"}

        # ==================================================
        # 🛡️ تفعيل الدرع الرياضي (Quant Shield) قبل التنفيذ
        # ==================================================
        regime = quant_report.get("market_regime", "RANDOM")
        hurst = quant_report.get("hurst_exponent", 0.5)
        z_score = quant_report.get("z_score", 0.0)

        # استراتيجيات الارتداد التي تعاني من الترند القوي
        is_reversion_strategy = executed_strategy in ["rsi_reversion", "smart_limits", "golden_setup"]

        # 1. منع التداول عكس الاتجاه القوي (الفلتر العام لجميع الأزواج)
        if is_reversion_strategy and regime == "TRENDING":
            system_logger.warning(
                f"🛡️ Quant Shield Activated: Blocked {final_decision} on {symbol}. "
                f"Market is violently TRENDING (Hurst={hurst:.2f}). Mean-reversion blocked!"
            )
            return {"status": "blocked", "decision": "HOLD", "message": "Blocked by Quant Shield (Trending Market)"}

        # 2. درع الانحراف المعياري (Z-Score) مخصص للذهب لخطورته
        if "XAU" in symbol:
            if final_decision in ["BUY", "BUY_LIMIT", "BUY_STOP"] and z_score > -1.0:
                system_logger.warning(
                    f"🛡️ Gold Quant Shield: Blocked BUY on {symbol}. "
                    f"Z-Score ({z_score:.2f}) is not low enough. Price hasn't dropped mathematically enough to buy safely."
                )
                return {"status": "blocked", "decision": "HOLD", "message": "Blocked by Quant Shield (Z-Score unsafe for BUY)"}
                
            elif final_decision in ["SELL", "SELL_LIMIT", "SELL_STOP"] and z_score < 1.0:
                system_logger.warning(
                    f"🛡️ Gold Quant Shield: Blocked SELL on {symbol}. "
                    f"Z-Score ({z_score:.2f}) is not high enough. Price hasn't risen mathematically enough to sell safely."
                )
                return {"status": "blocked", "decision": "HOLD", "message": "Blocked by Quant Shield (Z-Score unsafe for SELL)"}

        # ==================================================
        # 🎯 معالجة أمر التنفيذ النهائي
        # ==================================================
        system_logger.info(f"🎯 ACTUAL SIGNAL TRIGGERED: {final_decision} on {symbol} (Strategy: {executed_strategy})")

        entry = _safe_float(final_result.get("entry_price", 0.0))
        if entry <= 0:
            entry = _price(market_data, final_decision)

        sl_raw = _safe_float(final_result.get("sl", market_data.get("sl", 0.0)))
        tp_raw = _safe_float(final_result.get("tp", market_data.get("tp", 0.0)))
        sl, tp = _build_protection(market_data, final_decision, entry, sl_raw, tp_raw)
        
        if sl <= 0 or tp <= 0:
            return {"status": "blocked", "decision": "HOLD", "message": "No valid SL/TP"}

        if final_decision in ("BUY", "BUY_LIMIT", "BUY_STOP") and not (sl < entry < tp):
            return {"status": "blocked", "decision": "HOLD", "message": f"Invalid {final_decision} geometry: SL({sl}) < EN({entry}) < TP({tp})"}
        if final_decision in ("SELL", "SELL_LIMIT", "SELL_STOP") and not (tp < entry < sl):
            return {"status": "blocked", "decision": "HOLD", "message": f"Invalid {final_decision} geometry: TP({tp}) < EN({entry}) < SL({sl})"}

        calculated_lot_size = _calculate_dynamic_lot(symbol, entry, sl, market_data)
        if calculated_lot_size <= 0:
            return {"status": "blocked", "decision": "HOLD", "message": "Zero lot size calculated (Risk block)"}

        signal_key = f"{symbol}|{executed_strategy}|{timeframe}|{candle_key}|{final_decision}|{int(entry)}"

        command = schemas.CommandCreate(
            symbol=symbol,
            order_type=final_decision,
            lot_size=calculated_lot_size,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            strategy_name=executed_strategy,
            signal_key=signal_key,
            ea_id=str(market_data.get("ea_id") or ""),
        )

        created = await trade_service.process_new_command(
            db=db,
            command=command,
            account_id=account_id,
            enforce_risk=True,
        )

        system_logger.info(
            f"✅ COMMAND CREATED IN DB: {final_decision} on {symbol} | Strat: {executed_strategy} | Lot: {calculated_lot_size} | Entry: {entry} | SL: {sl} | TP: {tp}"
        )
        return {
            "status": "success",
            "decision": final_decision,
            "symbol": symbol,
            "command_id": str(created.id),
            "lot_size": created.lot_size,
        }
    except Exception as exc:
        system_logger.error("❌ Error in evaluate_and_execute_strategy for %s: %s", symbol, str(exc))
        return {"status": "blocked", "decision": "HOLD", "message": str(exc)}
