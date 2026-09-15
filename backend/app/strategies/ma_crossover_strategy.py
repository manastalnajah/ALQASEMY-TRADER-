from app.strategies.base_strategy import BaseStrategy
from app.logging.logger import system_logger

class MACrossoverStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="Moving Average Crossover (RELAXED TEST)")

    def analyze(self, market_data: dict):
        fast = market_data.get("fast_ma")
        slow = market_data.get("slow_ma")
        price = market_data.get("close")
        
        # إذا لم يتم حساب المؤشرات بعد، ننتظر
        if None in (fast, slow, price):
            return "HOLD"

        # ========================================================
        # 🚨 شروط مخففة جداً لاختبار النظام (Stress Test) 🚨
        # ========================================================
        # تم إلغاء فلتر الفريمات الكبيرة (market_bias) وتم إلغاء شرط "التقاطع اللحظي"
        
        # إذا كان السعر أسفل الموفينج السريع، والموفينج السريع أسفل البطيء = ترند هابط، بيع فوراً!
        if fast < slow and price < fast:
            system_logger.info(f"🚀 [TEST] Downtrend detected! Firing SELL for {market_data.get('symbol')}")
            return "SELL"
            
        # إذا كان السعر أعلى الموفينج السريع، والموفينج السريع أعلى البطيء = ترند صاعد، شراء فوراً!
        if fast > slow and price > fast:
            system_logger.info(f"🚀 [TEST] Uptrend detected! Firing BUY for {market_data.get('symbol')}")
            return "BUY"

        return "HOLD"
