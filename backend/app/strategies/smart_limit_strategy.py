import math
from app.strategies.base_strategy import BaseStrategy
from app.logging.logger import system_logger

class SmartLimitStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="smart_limits")

    def analyze(self, market_data: dict) -> dict:
        price = float(market_data.get("close") or 0)
        support = float(market_data.get("support") or 0)
        resistance = float(market_data.get("resistance") or 0)
        point = float(market_data.get("point") or 0)
        candles = market_data.get("candles", [])

        # حماية ضد نقص البيانات
        if price <= 0 or support <= 0 or resistance <= 0 or point <= 0 or not candles:
            return {"decision": "HOLD"}

        # التأكد من منطقية النطاق
        if resistance <= support:
            return {"decision": "HOLD"}
            
        range_points = (resistance - support) / point
        if range_points < 50:
            return {"decision": "HOLD"}

        # ==================================================
        # 🧮 المحرك الرياضي (استبعاد الافتراضات العشوائية)
        # ==================================================
        
        # استخراج إغلاقات الشموع لآخر فترة (هيكل السوق الحالي)
        recent_closes = [float(c.get("close", 0)) for c in candles[-40:]]
        
        if len(recent_closes) < 10:
             return {"decision": "HOLD"}

        # 1. حساب السعر العادل (Equilibrium / Mean)
        # هذا هو هدفنا الدقيق (الجاذب السعري) الذي سيعود إليه السعر حتماً في نفس اليوم
        equilibrium_price = sum(recent_closes) / len(recent_closes)

        # 2. حساب الانحراف المعياري (الضجيج السعري)
        # لتحديد مسافة الوقف بناءً على حركة السوق الحقيقية وليس نسبة ثابتة
        variance = sum((x - equilibrium_price) ** 2 for x in recent_closes) / len(recent_closes)
        # إجبار الانحراف المعياري (والوقف) على ألا يقل عن 20 نقطة كحد أدنى
        std_dev = max(math.sqrt(variance), point * 20.0)

        # تحديد مسافة التحفيز (Trigger Distance) لدخول الفخ
        distance_support = (price - support) / point
        distance_resistance = (resistance - price) / point
        trigger_points = min(50.0, max(10.0, range_points * 0.10))

        # ==================================================
        # 🎯 اتخاذ القرار المعلق (مع الأهداف الرياضية)
        # ==================================================

        if 0 <= distance_support <= trigger_points:
            # شراء من الدعم (الهدف هو المتوسط، والوقف هو الدعم ناقص الانحراف المعياري)
            calculated_sl = support - std_dev
            calculated_tp = equilibrium_price
            
            # حماية رياضية: إذا كان الهدف أقرب من الدخول بسبب ترند هابط قوي
            if calculated_tp <= support + (point * 30):
                calculated_tp = support + (std_dev * 1.5) # تحديد هدف ربح سريع للسكالبينج
                
            return {
                "decision": "BUY_LIMIT",
                "entry_price": round(support, 5),
                "sl": round(calculated_sl, 5),
                "tp": round(calculated_tp, 5),
            }
            
        if 0 <= distance_resistance <= trigger_points:
            # بيع من المقاومة (الهدف هو المتوسط، والوقف هو المقاومة زائد الانحراف المعياري)
            calculated_sl = resistance + std_dev
            calculated_tp = equilibrium_price
            
            # حماية رياضية: إذا كان الهدف أعلى من الدخول بسبب ترند صاعد قوي
            if calculated_tp >= resistance - (point * 30):
                calculated_tp = resistance - (std_dev * 1.5) # تحديد هدف ربح سريع للسكالبينج

            return {
                "decision": "SELL_LIMIT",
                "entry_price": round(resistance, 5),
                "sl": round(calculated_sl, 5),
                "tp": round(calculated_tp, 5),
            }

        return {"decision": "HOLD"}
