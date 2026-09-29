from sqlalchemy.orm import Session
from sqlalchemy import text
from app.strategies.strategy_manager import manager as strategy_manager
from app.services import trade_service
from app.domain import schemas
from app.logging.logger import system_logger
from app.config import config
from datetime import datetime, timezone


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


# 🚀 [إضافة مؤسسية] محرك رياضي داخلي لحساب RSI من قاعدة البيانات لضمان دقة الإشارات
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
    
    # حساب المتوسط المبدئي
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    # استخدام التنعيم (Smoothed Moving Average) بقية الفترات كما في منصات التداول
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def evaluate_and_execute_strategy(db: Session, account_id: str, strategy_name: str, market_data: dict):
    symbol = str(market_data.get("symbol") or "").upper()
    timeframe = str(market_data.get("timeframe") or getattr(config, "timeframe", "M5")).upper()
    candle_key = str(market_data.get("candle_key") or market_data.get("open_time") or "")

    if not symbol or not candle_key:
        return {"status": "ignored", "decision": "HOLD", "message": "Missing identity"}

    # ==================================================
    # التحقق من تفعيل الاستراتيجية مع دعم مرن للأسماء
    # ==================================================
    if strategy_name == "smart_limits" and not getattr(config, "allow_smart_limits", True):
        return {"status": "ignored", "decision": "HOLD", "message": "Smart limits disabled"}
    if strategy_name == "scalping" and not getattr(config, "allow_scalping", True):
        return {"status": "ignored", "decision": "HOLD", "message": "Scalping disabled"}
    if strategy_name in ("golden_setup", "Golden Setup") and not getattr(config, "allow_golden_setup", True):
        return {"status": "ignored", "decision": "HOLD", "message": "Golden Setup disabled"}

    # ==================================================
    # 🛡️️ فلتر 1: الساعة البيولوجية (أوقات السيولة المؤسساتية)
    # ==================================================
    current_utc_hour = datetime.now(timezone.utc).hour
    if not (8 <= current_utc_hour <= 17):
        system_logger.info(f"⏳ HOLD: {symbol} is outside institutional hours (Current UTC: {current_utc_hour})")
        return {"status": "ignored", "decision": "HOLD", "message": "Outside institutional liquidity hours"}

    # ==================================================
    # 🛡️ فلتر 2: كشف السيولة الوهمية (تم ضبطه بشكل ديناميكي)
    # ==================================================
    current_volume = _safe_float(market_data.get("volume"), 0.0)
    min_required_volume = getattr(config, "min_required_volume", 10.0)  # 🚀 التخفيض لمنع تجميد الإكسبيرت في فريمات M5
    if current_volume < min_required_volume:
        system_logger.info(f"📉 HOLD: {symbol} Fake liquidity detected (Low Volume: {current_volume} < {min_required_volume})")
        return {"status": "ignored", "decision": "HOLD", "message": f"Low Volume: {current_volume}"}

    try:
        decision = "HOLD"

        # ==================================================
        # 🧠 تنفيذ الاستراتيجيات
        # ==================================================
        if strategy_name == "rsi_reversion":
            # 🚀 استدعاء آخر 20 شمعة من الداتا بيز لحساب RSI دقيق جداً
            rows = db.execute(text("""
                SELECT close FROM candles 
                WHERE symbol_name = :sym AND timeframe = :tf 
                ORDER BY open_time DESC LIMIT 20
            """), {"sym": symbol, "tf": timeframe}).mappings().all()

            if len(rows) >= 15:
                # قلب المصفوفة لتكون الأقدم أولاً كما تتطلب معادلة RSI
                prices = [float(r["close"]) for r in rows][::-1]
                rsi_value = calculate_rsi(prices, period=14)
                
                oversold = getattr(config, "rsi_oversold_level", 30.0)
                overbought = getattr(config, "rsi_overbought_level", 70.0)
                
                # طباعة تفصيلية لقيمة المؤشر للشفافية
                system_logger.info(f"📊 {symbol} ({timeframe}) RSI(14) = {rsi_value:.2f}")

                if 0 < rsi_value <= oversold:
                    decision = "BUY"
                elif rsi_value >= overbought:
                    decision = "SELL"
            else:
                system_logger.info(f"⚠️ HOLD: Not enough candles in DB to calculate RSI for {symbol} (Found: {len(rows)})")
                
        else:
            # تنفيذ الاستراتيجيات الأخرى المعتادة 
            result = strategy_manager.execute(strategy_name, market_data)
            decision = str(result.get("decision", "HOLD")).upper() if isinstance(result, dict) else str(result).upper()

        if decision == "HOLD":
            return {"status": "success", "decision": "HOLD"}

        # ==================================================
        # 🎯 معالجة أمر التنفيذ عند صدور الإشارة
        # ==================================================
        system_logger.info(f"🎯 ACTUAL SIGNAL TRIGGERED: {decision} on {symbol} (Strategy: {strategy_name})")

        # 1. تحديد السعر الفعلي 
        entry = _price(market_data, decision)

        # 2. بناء مستويات الحماية
        sl_raw = _safe_float(market_data.get("sl", 0.0))
        tp_raw = _safe_float(market_data.get("tp", 0.0))
        sl, tp = _build_protection(market_data, decision, entry, sl_raw, tp_raw)
        
        if sl <= 0 or tp <= 0:
            return {"status": "blocked", "decision": "HOLD", "message": "No valid SL/TP"}

        # 3. التحقق النهائي من هندسة الصفقة
        if decision.startswith("BUY") and not (sl < entry < tp):
            return {"status": "blocked", "decision": "HOLD", "message": f"Invalid BUY geometry: SL({sl}) < EN({entry}) < TP({tp})"}
        if decision.startswith("SELL") and not (tp < entry < sl):
            return {"status": "blocked", "decision": "HOLD", "message": f"Invalid SELL geometry: TP({tp}) < EN({entry}) < SL({sl})"}

        # 4. حساب اللوت 
        calculated_lot_size = _calculate_dynamic_lot(symbol, entry, sl, market_data)
        if calculated_lot_size <= 0:
            return {"status": "blocked", "decision": "HOLD", "message": "Zero lot size calculated (Risk block)"}

        signal_key = f"{symbol}|{strategy_name}|{timeframe}|{candle_key}|{decision}"

        command = schemas.CommandCreate(
            symbol=symbol,
            order_type=decision,
            lot_size=calculated_lot_size,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            strategy_name=strategy_name,
            signal_key=signal_key,
            ea_id=str(market_data.get("ea_id") or ""),
        )

        created = trade_service.process_new_command(
            db=db,
            command=command,
            account_id=account_id,
            enforce_risk=True,
        )

        system_logger.info(
            f"✅ COMMAND CREATED IN DB: {decision} on {symbol} | Lot: {calculated_lot_size} | Entry: {entry} | SL: {sl} | TP: {tp}"
        )
        return {
            "status": "success",
            "decision": decision,
            "symbol": symbol,
            "command_id": str(created.id),
            "lot_size": created.lot_size,
        }
    except Exception as exc:
        system_logger.error("❌ Error in evaluate_and_execute_strategy for %s: %s", symbol, str(exc))
        return {"status": "blocked", "decision": "HOLD", "message": str(exc)}
