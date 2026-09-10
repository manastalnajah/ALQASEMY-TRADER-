from app.strategies.base_strategy import BaseStrategy
from app.logging.logger import system_logger

class SmartLimitStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="Smart Support & Resistance Limits")

    def analyze(self, market_data: dict) -> dict:
        current_price = market_data.get("close")
        support = market_data.get("support")
        resistance = market_data.get("resistance")
        symbol = market_data.get("symbol")

        if not current_price or not support or not resistance:
            system_logger.warning("⚠️ بيانات الدعوم والمقاومات غير مكتملة -> HOLD")
            return {"decision": "HOLD"}

        # تحديد قيمة النقطة (Pip) حسب الزوج
        pip_value = 0.1 if symbol.upper() == "XAUUSD" else 0.0001
        
        # حساب المسافة بين السعر الحالي والحدود
        distance_to_support = (current_price - support) / pip_value
        distance_to_resistance = (resistance - current_price) / pip_value

        # ==========================================
        # 🛑 متى يتوقف البوت عن التداول؟ (حالة اللاحسم)
        # ==========================================
        # إذا كان السعر في منتصف المسافة تماماً (منطقة عشوائية)، البوت يرفض التداول
        if distance_to_support > 200 and distance_to_resistance > 200:
            system_logger.info(f"⏳ السعر في المنتصف العشوائي لـ {symbol}. ننتظر اقترابه من الحدود -> HOLD")
            return {"decision": "HOLD"}

        # ==========================================
        # 🎯 قرار اصطياد الارتداد (أوامر معلقة)
        # ==========================================
        # إذا اقترب السعر من القاع (الدعم) وبدأ يلامسه، نتوقع توقف الهبوط ونضع BUY LIMIT
        if distance_to_support <= 50:
            system_logger.info(f"📉 اقترب السعر من دعم تاريخي ({support}). تجهيز أمر شراء معلق (BUY LIMIT)")
            return {
                "decision": "BUY_LIMIT",
                "entry_price": support,
                "sl": support - (30 * pip_value),  # وقف الخسارة تحت الدعم بـ 30 نقطة
                "tp": support + (100 * pip_value)  # الهدف 100 نقطة ارتداد للأعلى
            }

        # إذا اقترب السعر من القمة (المقاومة) نتوقع توقف الصعود ونضع SELL LIMIT
        elif distance_to_resistance <= 50:
            system_logger.info(f"📈 اقترب السعر من مقاومة تاريخية ({resistance}). تجهيز أمر بيع معلق (SELL LIMIT)")
            return {
                "decision": "SELL_LIMIT",
                "entry_price": resistance,
                "sl": resistance + (30 * pip_value), # وقف الخسارة فوق المقاومة بـ 30 نقطة
                "tp": resistance - (100 * pip_value) # الهدف 100 نقطة ارتداد للأسفل
            }

        return {"decision": "HOLD"}
