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

        # الخوارزمية: استغلال التشبع (Overbought / Oversold)
        if rsi_value >= 70:
            system_logger.info(f"📉 تشبع شرائي (RSI={rsi_value})! توقع هبوط -> SELL")
            return "SELL"
        elif rsi_value <= 30:
            system_logger.info(f"📈 تشبع بيعي (RSI={rsi_value})! توقع صعود -> BUY")
            return "BUY"
            
        return "HOLD"