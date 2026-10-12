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

# 🚀 استدعاء المحركات المؤسسية
from app.services.quant_analyzer import QuantAnalyzer
from app.services.market_structure_engine import MarketStructureEngine

quant_analyzer = QuantAnalyzer()
msce = MarketStructureEngine(quant_analyzer)

def _safe_float(val, default: float = 0.0) -> float:
    if val is None: return default
    if hasattr(val, "iloc"): val = val.iloc[-1]
    elif isinstance(val, (list, tuple)) and len(val) > 0: val = val[-1]
    try: return float(val)
    except (TypeError, ValueError): return default

def _price(market_data: dict, decision: str) -> float:
    if decision.startswith("BUY"): return _safe_float(market_data.get("ask") or market_data.get("close") or 0.0)
    elif decision.startswith("SELL"): return _safe_float(market_data.get("bid") or market_data.get("close") or 0.0)
    return _safe_float(market_data.get("close", 0.0))

def _build_protection(market_data: dict, decision: str, entry: float, sl: float, tp: float):
    if sl > 0 and tp > 0:
        calculated_sl, calculated_tp = sl, tp
    else:
        atr = _safe_float(market_data.get("atr"), 0.0)
        symbol = str(market_data.get("symbol", "")).upper()
        if atr <= 0: atr = 2.0 if "XAU" in symbol else 0.0030

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
    
    min_distance = 150.0 * point_size
    current_distance = abs(entry - calculated_sl)

    if current_distance < min_distance:
        system_logger.warning(f"🛡️ Protection Adjusted: SL distance expanded to minimum safe distance for {symbol}.")
        if decision.startswith("BUY"): calculated_sl = entry - min_distance
        elif decision.startswith("SELL"): calculated_sl = entry + min_distance

    return round(calculated_sl, 5), round(calculated_tp, 5)

def _calculate_dynamic_lot(symbol: str, entry: float, sl: float, market_data: dict) -> float:
    balance = _safe_float(market_data.get("balance") or market_data.get("equity"))
    if balance <= 0: return 0.0

    risk_amount = balance * (getattr(config, "risk_per_trade_pct", 1.0) / 100.0)
    sl_distance = abs(entry - sl)
    if sl_distance <= 0: return 0.01

    tick_size = _safe_float(market_data.get("tick_size"), 0.0)
    tick_value = _safe_float(market_data.get("tick_value"), 0.0)

    if tick_size > 0 and tick_value > 0:
        lot_size = risk_amount / ((sl_distance / tick_size) * tick_value)
    else:
        lot_size = risk_amount / (sl_distance * (100 if "XAU" in symbol else 1000 if "JPY" in symbol else 100000))

    return max(0.01, min(round(lot_size, 2), getattr(config, "max_symbol_exposure_lots", 5.0)))

def calculate_rsi(prices: list, period: int = 14) -> float:
    if len(prices) < period + 1: return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        gains.append(change if change > 0 else 0.0)
        losses.append(abs(change) if change < 0 else 0.0)
    
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
    if avg_loss == 0: return 100.0
    return 100.0 - (100.0 / (1.0 + (avg_gain / avg_loss)))

# ==================================================
# 🛠️ الدالة الرئيسية - الخنق المعماري وإدارة الطوارئ
# ==================================================
async def evaluate_and_execute_strategy(db: AsyncSession, account_id: str, strategy_name: str, market_data: dict):
    symbol = str(market_data.get("symbol") or "").upper()
    timeframe = str(market_data.get("timeframe") or getattr(config, "timeframe", "M5")).upper()
    candle_key = str(market_data.get("candle_key") or market_data.get("open_time") or "")

    if not symbol or not candle_key:
        return {"status": "ignored", "decision": "HOLD", "message": "Missing identity"}

    current_utc_hour = datetime.now(timezone.utc).hour
    if not (7 <= current_utc_hour <= 21):
        return {"status": "ignored", "decision": "HOLD"}

    # ==================================================
    # 🚀 جلب البيانات المؤسسية (Data Integrity Check)
    # المبدأ: لا نقرأ المستقبل (is_closed = true) ونجلب 100 شمعة
    # ==================================================
    try:
        # إطار M5 (أساسي)
        rows_m5 = (await db.execute(text("""
            SELECT open_time, open, high, low, close, volume 
            FROM candles WHERE symbol_name = :sym AND timeframe = :tf AND is_closed = true
            ORDER BY open_time DESC LIMIT 150
        """), {"sym": symbol, "tf": timeframe})).mappings().all()
        candles_list = [dict(r) for r in rows_m5][::-1]
        market_data["candles"] = candles_list

        # إطار M15 لمحرك البنية (100 شمعة لإيجاد سوينجات حقيقية)
        rows_m15 = (await db.execute(text("""
            SELECT open_time, open, high, low, close 
            FROM candles WHERE symbol_name = :sym AND timeframe = 'M15' AND is_closed = true
            ORDER BY open_time DESC LIMIT 100
        """), {"sym": symbol})).mappings().all()
        candles_m15 = [dict(r) for r in rows_m15][::-1]

        # إطار H1 لمحرك البنية (100 شمعة)
        rows_h1 = (await db.execute(text("""
            SELECT open_time, open, high, low, close 
            FROM candles WHERE symbol_name = :sym AND timeframe = 'H1' AND is_closed = true
            ORDER BY open_time DESC LIMIT 100
        """), {"sym": symbol})).mappings().all()
        candles_h1 = [dict(r) for r in rows_h1][::-1]

        if len(candles_list) >= 40:
            market_data["support"] = min(float(c["low"]) for c in candles_list[-40:])
            market_data["resistance"] = max(float(c["high"]) for c in candles_list[-40:])
        else:
            market_data["support"], market_data["resistance"] = 0.0, 0.0
        
        market_data["point"] = _safe_float(market_data.get("tick_size"), 0.00001)

    except Exception as e:
        system_logger.error(f"❌ Error preparing historical data for {symbol}: {e}")
        return {"status": "error", "decision": "HOLD"}

    # ==================================================
    # 🧮 توليد خريطة السوق
    # ==================================================
    close_prices = [float(c["close"]) for c in candles_list]
    quant_report = quant_analyzer.analyze_single_asset(close_prices)
    structure_report = msce.analyze_structure(candles_h1, candles_m15, candles_list)
    z_score = quant_report.get("z_score", 0.0)

    # ==================================================
    # 🛡️ نظام المراقبة النشطة (Active Trade Management)
    # ==================================================
    account_number_int = int(market_data.get("account_number", 0))
    if account_number_int > 0:
        open_position = (await db.execute(text("""
            SELECT ticket, position_type, volume 
            FROM open_positions 
            WHERE symbol = :sym AND account_number = :acc
            LIMIT 1
        """), {"sym": symbol, "acc": account_number_int})).mappings().first()

        if open_position:
            pos_ticket = int(open_position["ticket"])
            pos_type = str(open_position["position_type"]).upper()
            pos_side = "BUY" if pos_type in ["0", "BUY"] else "SELL"

            eval_pos = msce.evaluate_open_position(pos_side, structure_report, quant_report)

            if eval_pos["action"] == "CLOSE":
                system_logger.warning(f"🚨 BAILOUT TRIGGERED: Closing {pos_side} on {symbol} - {eval_pos['reason']}")
                try:
                    await trade_service.process_position_command(
                        db=db,
                        account_id=account_id,
                        account_number=account_number_int,
                        ea_id=str(market_data.get("ea_id") or ""),
                        position_ticket=pos_ticket,
                        symbol=symbol,
                        action="CLOSE_POSITION",
                        reason=eval_pos["reason"]
                    )
                    system_logger.info(f"✅ CLOSE_POSITION command sent successfully for ticket {pos_ticket}")
                except Exception as e:
                    system_logger.error(f"❌ Failed to send CLOSE command: {e}")

            return {"status": "managing", "decision": "HOLD", "message": "Managing existing open position"}

    try:
        active_strategies = ["rsi_reversion", "golden_setup", "smart_limits"]
        final_decision, final_result, executed_strategy = "HOLD", {}, ""

        for strat in active_strategies:
            decision, result = "HOLD", {}

            if strat == "smart_limits" and not getattr(config, "allow_smart_limits", True): continue
            if strat == "golden_setup" and not getattr(config, "allow_golden_setup", True): continue

            # توليد الإشارة الأولية
            if strat == "rsi_reversion":
                if len(candles_list) >= 15:
                    rsi_value = calculate_rsi(close_prices, period=14)
                    if 0 < rsi_value <= getattr(config, "rsi_oversold_level", 30.0): decision = "BUY"
                    elif rsi_value >= getattr(config, "rsi_overbought_level", 70.0): decision = "SELL"
            else:
                result = strategy_manager.execute(strat, market_data)
                decision = str(result.get("decision", "HOLD")).upper() if isinstance(result, dict) else str(result).upper()

            # --------------------------------------------------
            # 🛡️ الحراسة المعمارية (MSCE Gatekeeper)
            # --------------------------------------------------
            if decision != "HOLD":
                candidate = {"signal": decision, "strategy": strat}
                
                # 1. التقييم البنيوي الصارم (H1, M15, M5, BOS)
                eval_res = msce.evaluate_candidate(candidate, structure_report, quant_report)
                if not eval_res.get("approved", False):
                    system_logger.info(
                        f"🚫 MSCE [{symbol}] | Strat: {strat} | Signal: {decision} | "
                        f"H1: {structure_report['H1']['trend']} | M15: {structure_report['M15']['trend']} | "
                        f"Action: REJECTED | Reason: {eval_res.get('reason')}"
                    )
                    continue # فشل، انتقل للاستراتيجية التالية

                # 2. درع زِد سكور الكمي للذهب
                if "XAU" in symbol:
                    if decision.startswith("BUY") and z_score > -1.0:
                        system_logger.warning(f"🛡️ Quant Block [{symbol}]: BUY rejected (Z-Score {z_score:.2f} not low enough)")
                        continue
                    elif decision.startswith("SELL") and z_score < 1.0:
                        system_logger.warning(f"🛡️ Quant Block [{symbol}]: SELL rejected (Z-Score {z_score:.2f} not high enough)")
                        continue

                # تم اجتياز كافة الدروع بنجاح
                final_decision, final_result, executed_strategy = decision, result if isinstance(result, dict) else {}, strat
                break 

        # ==================================================
        # 🎯 مرحلة بناء الأمر وإرساله
        # ==================================================
        if final_decision == "HOLD":
            return {"status": "success", "decision": "HOLD"}

        system_logger.info(
            f"✅ ACTUAL SIGNAL APPROVED: {final_decision} on {symbol} (Strategy: {executed_strategy})\n"
            f"   Context -> H1: {structure_report['H1']['trend']} | M15: {structure_report['M15']['trend']} | M15 BOS: {structure_report['M15']['bos']}"
        )

        entry = _safe_float(final_result.get("entry_price", 0.0))
        if entry <= 0: entry = _price(market_data, final_decision)

        sl_raw = _safe_float(final_result.get("sl", market_data.get("sl", 0.0)))
        tp_raw = _safe_float(final_result.get("tp", market_data.get("tp", 0.0)))
        
        sl, tp = _build_protection(market_data, final_decision, entry, sl_raw, tp_raw)
        if sl <= 0 or tp <= 0: return {"status": "blocked", "decision": "HOLD", "message": "Invalid SL/TP"}

        calculated_lot_size = _calculate_dynamic_lot(symbol, entry, sl, market_data)
        if calculated_lot_size <= 0: return {"status": "blocked", "decision": "HOLD", "message": "Risk block: Lot <= 0"}

        command = schemas.CommandCreate(
            symbol=symbol, order_type=final_decision, lot_size=calculated_lot_size,
            entry_price=entry, stop_loss=sl, take_profit=tp, strategy_name=executed_strategy,
            signal_key=f"{symbol}|{executed_strategy}|{timeframe}|{candle_key}|{final_decision}",
            ea_id=str(market_data.get("ea_id") or ""),
            account_number=int(market_data.get("account_number")) if market_data.get("account_number") else None
        )

        created = await trade_service.process_new_command(db=db, command=command, account_id=account_id, enforce_risk=True)

        system_logger.info(f"🚀 EXECUTION SENT: {final_decision} {symbol} | Lot: {calculated_lot_size} | Entry: {entry}")
        return {"status": "success", "decision": final_decision, "symbol": symbol, "command_id": str(created.id), "lot_size": created.lot_size}

    except Exception as exc:
        system_logger.error(f"❌ Error in evaluator for {symbol}: {exc}")
        return {"status": "blocked", "decision": "HOLD", "message": str(exc)}
