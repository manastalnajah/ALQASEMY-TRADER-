from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.strategies.strategy_manager import manager as strategy_manager
from app.services import trade_service
from app.domain import schemas
from app.logging.logger import system_logger
from app.config import config
from app.indicators.atr import calculate_atr


def _price(market_data: dict) -> float:
    return float(market_data.get("close") or market_data.get("price") or 0.0)


def _build_protection(market_data: dict, decision: str, entry: float, sl: float, tp: float):
    if sl > 0 and tp > 0:
        return sl, tp
    atr = float(market_data.get("atr") or 0.0)
    if atr <= 0:
        return 0.0, 0.0
    risk_distance = atr * config.atr_sl_multiplier
    
    if decision.startswith("BUY"):
        return entry - risk_distance, entry + (risk_distance * config.reward_risk)
    if decision.startswith("SELL"):
        return entry + risk_distance, entry - (risk_distance * config.reward_risk)
    return 0.0, 0.0


def _calculate_dynamic_lot(db: Session, account_id: str, symbol: str, entry: float, sl: float, market_data: dict) -> float:
    """
    حساب اللوت الديناميكي باحترافية بناءً على نسبة المخاطرة والـ ATR
    """
    # 1. جلب رأس المال (إذا كان متوفراً في الداتا، أو وضع 10000 كافتراضي لحمايتك)
    balance = float(market_data.get("balance") or market_data.get("equity") or 10000.0)
    
    # 2. حساب المبلغ المعرض للمخاطرة (مثلاً 0.5% من 10,000 = 50 دولار)
    risk_amount = balance * (config.risk_per_trade_pct / 100.0)
    
    # 3. حساب المسافة بين نقطة الدخول ووقف الخسارة
    sl_distance = abs(entry - sl)
    if sl_distance <= 0:
        return 0.01  # أقل لوت ممكن لحماية الحساب إذا كان الوقف غير منطقي

    # 4. حساب اللوت بناءً على خصائص الزوج (Tick Size & Tick Value)
    tick_size = float(market_data.get("tick_size") or 0.0)
    tick_value = float(market_data.get("tick_value") or 0.0)
    
    if tick_size > 0 and tick_value > 0:
        # حساب احترافي دقيق من بيانات البروكر
        ticks_at_risk = sl_distance / tick_size
        lot_size = risk_amount / (ticks_at_risk * tick_value)
    else:
        # حساب تقريبي قياسي في حال لم تتوفر بيانات البروكر لحظياً
        if "XAU" in symbol:
            lot_size = risk_amount / (sl_distance * 100)
        elif "JPY" in symbol:
            lot_size = risk_amount / (sl_distance * 1000)
        else:
            lot_size = risk_amount / (sl_distance * 100000)

    # 5. تنظيف الرقم ليتوافق مع منصة الميتاتريدر
    lot_size = round(lot_size, 2)
    
    # 6. فرض الحدود الآمنة (Min / Max)
    if lot_size < 0.01:
        lot_size = 0.01
    if lot_size > config.max_symbol_exposure_lots:
        lot_size = config.max_symbol_exposure_lots
        
    return lot_size


def evaluate_and_execute_strategy(db: Session, account_id: str, strategy_name: str, market_data: dict):
    symbol = str(market_data.get("symbol") or "").upper()
    timeframe = str(market_data.get("timeframe") or config.timeframe).upper()
    candle_key = str(market_data.get("candle_key") or market_data.get("open_time") or "")
    
    if not symbol or not candle_key:
        return {"status": "ignored", "decision": "HOLD", "message": "Missing symbol/candle identity"}

    if strategy_name == "smart_limits" and not config.allow_smart_limits:
        return {"status": "ignored", "decision": "HOLD", "message": "Smart limits disabled"}
    if strategy_name == "scalping" and not config.allow_scalping:
        return {"status": "ignored", "decision": "HOLD", "message": "Scalping disabled"}

    try:
        result = strategy_manager.execute(strategy_name, market_data)
        if isinstance(result, dict):
            decision = str(result.get("decision", "HOLD")).upper()
            entry = float(result.get("entry_price", 0.0) or 0.0)
            sl = float(result.get("sl", 0.0) or 0.0)
            tp = float(result.get("tp", 0.0) or 0.0)
        else:
            decision = str(result).upper()
            entry, sl, tp = 0.0, 0.0, 0.0

        if decision == "HOLD":
            return {"status": "success", "decision": "HOLD"}

        current = _price(market_data)
        if entry <= 0:
            entry = current
        
        sl, tp = _build_protection(market_data, decision, entry, sl, tp)
        if sl <= 0 or tp <= 0:
            system_logger.warning("🛑 %s %s rejected: no valid SL/TP", strategy_name, symbol)
            return {"status": "blocked", "decision": "HOLD", "message": "No valid SL/TP"}

        if decision.startswith("BUY") and not (sl < entry < tp):
            return {"status": "blocked", "decision": "HOLD", "message": "Invalid BUY protection geometry"}
        if decision.startswith("SELL") and not (tp < entry < sl):
            return {"status": "blocked", "decision": "HOLD", "message": "Invalid SELL protection geometry"}

        # 💡 استدعاء دالة حساب اللوت الديناميكي التي برمجناها
        calculated_lot_size = _calculate_dynamic_lot(db, account_id, symbol, entry, sl, market_data)

        signal_key = f"{symbol}|{strategy_name}|{timeframe}|{candle_key}|{decision}"
        
        command = schemas.CommandCreate(
            symbol=symbol,
            order_type=decision,
            lot_size=calculated_lot_size,  # 🔥 تم استبدال 1.0 باللوت الديناميكي
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
            enforce_risk=True
        )

        return {
            "status": "success",
            "decision": decision,
            "symbol": symbol,
            "command_id": str(created.id),
            "lot_size": created.lot_size,
            "entry_price": created.entry_price,
            "stop_loss": created.stop_loss,
            "take_profit": created.take_profit,
        }
    except Exception as exc:
        # 🛠️ التقاط أي خطأ زمني أو قاعدة بيانات لمنع توقف حلقة التداول ومعرفة السبب بدقة
        system_logger.error("❌ Error in evaluate_and_execute_strategy for %s: %s", symbol, str(exc))
        return {"status": "blocked", "decision": "HOLD", "message": str(exc)}
