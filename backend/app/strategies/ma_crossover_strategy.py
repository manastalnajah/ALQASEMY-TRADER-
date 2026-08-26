from app.strategies.base_strategy import BaseStrategy
from app.logging.logger import system_logger

class MACrossoverStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="Moving Average Crossover")

    def analyze(self, market_data: dict) -> str:
        system_logger.info(f"🔍 تحليل السوق باستراتيجية: {self.name}")
        
        # استخراج المتوسط السريع (مثلاً 50) والبطيء (مثلاً 200)
        fast_ma = market_data.get("fast_ma")
        slow_ma = market_data.get("slow_ma")

        if not fast_ma or not slow_ma:
            system_logger.warning("⚠️ بيانات المتوسطات غير مكتملة، القرار: HOLD")
            return "HOLD"

        # الخوارزمية: التقاطع الذهبي (شراء) والتقاطع الميت (بيع)
        if fast_ma > slow_ma:
            system_logger.info("📈 تقاطع ذهبي! السريع أعلى من البطيء -> BUY")
            return "BUY"
        elif fast_ma < slow_ma:
            system_logger.info("📉 تقاطع ميت! السريع أقل من البطيء -> SELL")
            return "SELL"
            
        return "HOLD"