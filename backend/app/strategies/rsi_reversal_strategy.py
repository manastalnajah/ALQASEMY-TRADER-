from app.strategies.base_strategy import BaseStrategy
from app.logging.logger import system_logger

class RSIReversalStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="RSI Mean Reversion")

    def analyze(self, market_data: dict) -> str:
        system_logger.info(f"🔍 تحليل السوق باستراتيجية: {self.name}")
        
        rsi_value = market_data.get("rsi")

        if not rsi_value:
            system_logger.warning("⚠️ بيانات مؤشر RSI مفقودة، القرار: HOLD")
            return "HOLD"

        # 🛠️ [وضع الاختبار]: تم تقليل الشروط جداً لإجبار البوت على فتح صفقات فورية
        # إذا كان المؤشر 50 أو أكثر، سيفتح صفقة بيع مباشرة
        if rsi_value >= 50:
            system_logger.info(f"📉 (وضع الاختبار) إشارة سريعة (RSI={rsi_value})! توقع هبوط -> SELL")
            return "SELL"
            
        # إذا كان المؤشر أقل من 50، سيفتح صفقة شراء مباشرة
        elif rsi_value < 50:
            system_logger.info(f"📈 (وضع الاختبار) إشارة سريعة (RSI={rsi_value})! توقع صعود -> BUY")
            return "BUY"
            
        return "HOLD"
