from app.strategies.base_strategy import BaseStrategy
from app.logging.logger import system_logger

class RSIReversalStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="RSI Mean Reversion")

    def analyze(self, market_data: dict) -> str:
        system_logger.info(f"🔍 تحليل السوق باستراتيجية: {self.name}")
        
        rsi_value = market_data.get("rsi")

        if rsi_value is None:
            system_logger.warning("⚠️ بيانات مؤشر RSI مفقودة، القرار: HOLD")
            return "HOLD"

        # 🎯 الاستراتيجية الاحترافية الحقيقية (Mean Reversion) بدون أي اختبارات وهمية
        # الشراء فقط عند التشبع البيعي الحقيقي
        if rsi_value < 30:
            system_logger.info(f"📈 [إشارة حقيقية] تشبع بيعي (RSI={rsi_value:.2f})! توقع صعود -> BUY")
            return "BUY"
            
        # البيع فقط عند التشبع الشرائي الحقيقي
        elif rsi_value > 70:
            system_logger.info(f"📉 [إشارة حقيقية] تشبع شرائي (RSI={rsi_value:.2f})! توقع هبوط -> SELL")
            return "SELL"
            
        # أي قيمة بين 30 و 70 تعني الحياد التام والانتظار بصمت
        return "HOLD"
