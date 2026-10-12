from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.strategies.strategy_manager import manager as strategy_manager
from app.services import trade_service
from app.domain import schemas
from app.logging.logger import system_logger
from app.config import config

# 🚀 استدعاء المحركات (الكمي + بنية السوق)
from app.services.quant_analyzer import QuantAnalyzer
from app.services.market_structure_engine import MarketStructureEngine

quant_analyzer = QuantAnalyzer()
msce = MarketStructureEngine(quant_analyzer)


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
        calculated_sl = sl
        calculated_tp = tp
    else:
        atr = _safe_float(market_data.get("atr"), 0.0)
        symbol = str(market_data.get("symbol", "")).upper()

        if atr <= 0:
            atr = 2.0 if "XAU" in symbol else 0.0030

        risk_distance = atr * getattr(config, "atr_sl_multiplier", 1.5)
        rr = getattr(config, "reward_risk", 1.5)

        if decision.startswith("BUY"):
            calculated_sl = entry - risk_distance
            calculated_tp = entry + (risk_distance * rr)
        elif decision.startswith("SELL"):
            calculated_sl = entry + risk_distance
            calculated_tp = entry - (risk_distance * rr)
        else:
            return 0.0, 0.0

    # 🛡️ صمام الأمان الرياضي (Minimum Stop Loss Distance)
    symbol = str(market_data.get("symbol", "")).upper()
    point_size = 0.01 if "XAU" in symbol or "JPY" in symbol else 0.00001
    
    MINIMUM_SL_POINTS = 150.0 
    min_distance = MINIMUM_SL_POINTS * point_size
    current_distance = abs(entry - calculated_sl)

    if current_distance < min_distance:
        system_logger.warning(
            f"🛡️ Protection Adjusted: SL distance ({current_distance:.5f}) was too tight for {symbol}. "
            f"Expanding to minimum safe distance ({min_distance:.5f})."
        )
        if decision.startswith("BUY"):
            calculated_sl = entry - min_distance
        elif decision.startswith("SELL"):
            calculated_sl = entry + min_distance

    return round(calculated_sl, 5), round(calculated_tp, 5)


def _calculate_dynamic_lot(symbol: str, entry: float, sl: float, market_data: dict) -> float:
    """الحساب المبدئي للوت (سيتم تدقيقه في trade_service لاحقاً)"""
    balance_raw = market_data.get("balance") or market_data.get("equity")
    if balance_raw is None:
        system_logger.error(f"🛑 CRITICAL: Balance not found for {symbol}. Blocking execution.")
        return 0.0 

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
        lot_size = risk_amount / (sl_distance * (100 if "XAU" in symbol else 1000 if "JPY" in symbol else 100000))

    lot_size = round(lot_size, 2)
    max_lots = getattr(config, "max_symbol_exposure_lots", 5.0)
    return max(0.01, min(lot_size, max_lots))


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


# ==================================================
# 🛠️ الدالة الرئيسية لتنفيذ وتقييم الاستراتيجيات مع بوابة MSCE
# ==================================================
async def evaluate_and_execute_strategy(db: AsyncSession, account_id: str, strategy_name: str, market_data: dict):
    symbol = str(market_data.get("symbol") or "").upper()
    timeframe = str(market_data.get("timeframe") or getattr(config, "timeframe", "M5")).upper()
    candle_key = str(market_data.get("candle_key") or market_data.get("open_time") or "")

    if not symbol or not candle_key:
        return {"status": "ignored", "decision": "HOLD", "message": "Missing identity"}

    # 🛡️ فلتر أوقات الجلسات العالمية הפعالة
    current_utc_hour = datetime.now(timezone.utc).hour
    if not (7 <= current_utc_hour <= 21):
        system_logger.info(f"⏳ HOLD: {symbol} is outside active session hours (Current UTC: {current_utc_hour}).")
        return {"status": "ignored", "decision": "HOLD", "message": "Outside active market sessions"}

    # ==================================================
    # 🚀 جلب البيانات للأطر الزمنية المختلفة لتعمل كأدلة
    # ==================================================
    try:
        # 1. إطار العمل الأساسي (M5 عادةً)
        rows_main = (await db.execute(text("""
            SELECT open_time, open, high, low, close, volume 
            FROM candles 
            WHERE symbol_name = :sym AND timeframe = :tf 
            ORDER BY open_time DESC LIMIT 150
        """), {"sym": symbol, "tf": timeframe})).mappings().all()

        candles_list = [dict(r) for r in rows_main][::-1]
        market_data["candles"] = candles_list

        # 2. إطار M15 لمحرك بنية السوق
        rows_m15 = (await db.execute(text("""
            SELECT open_time, open, high, low, close 
            FROM candles 
            WHERE symbol_name = :sym AND timeframe = 'M15' 
            ORDER BY open_time DESC LIMIT 20
        """), {"sym": symbol})).mappings().all()
        candles_m15 = [dict(r) for r in rows_m15][::-1]

        # 3. إطار H1 لمحرك بنية السوق
        rows_h1 = (await db.execute(text("""
            SELECT open_time, open, high, low, close 
            FROM candles 
            WHERE symbol_name = :sym AND timeframe = 'H1' 
            ORDER BY open_time DESC LIMIT 20
        """), {"sym": symbol})).mappings().all()
        candles_h1 = [dict(r) for r in rows_h1][::-1]

        # الدعوم والمقاومات
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
    # 🧮 توليد التقارير: الكمي (Quant) و البنيوي (MSCE)
    # ==================================================
    close_prices = [float(c["close"]) for c in candles_list]
    quant_report = quant_analyzer.analyze_single_asset(close_prices)
    structure_report = msce.analyze_structure(candles_h1, candles_m15)
    z_score = quant_report.get("z_score", 0.0)

    try:
        # ==================================================
        # 🧠 حلقة العقول المدبرة: الاستراتيجيات تقترح، والمحرك يقرر
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

            # توليد الإشارة
            if strat == "rsi_reversion":
                if len(rows_main) >= 15:
                    prices = [float(r["close"]) for r in rows_main][::-1]
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

            # --------------------------------------------------
            # 🛡️ بوابة التأكيد (إذا كانت هناك إشارة مقترحة)
            # --------------------------------------------------
            if decision != "HOLD":
                candidate = {"signal": decision, "strategy": strat}
                
                # 1. فحص بنية السوق (MSCE Gatekeeper)
                evaluation = msce.evaluate_candidate(candidate, structure_report, quant_report)
                if not evaluation.get("approved", False):
                    system_logger.info(f"🚫 MSCE Rejected {decision} from {strat}: {evaluation.get('reason')}")
                    # ننتقل لفحص الاستراتيجية التالية ولا نوقف الحلقة!
                    continue

                # 2. درع الانحراف المعياري الخاص بالذهب (Quant Shield)
                if "XAU" in symbol:
                    if decision in ["BUY", "BUY_LIMIT", "BUY_STOP"] and z_score > -1.0:
                        system_logger.warning(f"🛡️ Gold Quant Shield: Blocked {decision} on {symbol} (Z-Score {z_score:.2f} unsafe)")
                        continue
                    elif decision in ["SELL", "SELL_LIMIT", "SELL_STOP"] and z_score < 1.0:
                        system_logger.warning(f"🛡️ Gold Quant Shield: Blocked {decision} on {symbol} (Z-Score {z_score:.2f} unsafe)")
                        continue

                # إذا نجحت الإشارة في اجتياز جميع البوابات
                final_decision = decision
                final_result = result if isinstance(result, dict) else {}
                executed_strategy = strat
                break # وجدنا إشارة صحيحة ומؤكدة، نتوقف عن فحص باقي الاستراتيجيات

        # ==================================================
        # 🎯 مرحلة بناء الأمر إذا تم اعتماد قرار
        # ==================================================
        if final_decision == "HOLD":
            return {"status": "success", "decision": "HOLD"}

        system_logger.info(f"🎯 ACTUAL SIGNAL APPROVED: {final_decision} on {symbol} (Strategy: {executed_strategy})")

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

        signal_key = f"{symbol}|{executed_strategy}|{timeframe}|{candle_key}|{final_decision}"

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
            account_number=int(market_data.get("account_number")) if market_data.get("account_number") else None
        )

        # الإرسال لـ trade_service حيث سيتم تفعيل محرك إدارة المخاطر النهائي (validate_and_size)
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
