# app/strategies/rsi_reversal.py
from app.strategies.base_strategy import BaseStrategy

class RSIReversalStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="RSI Mean Reversion")

    def analyze(self, market_data: dict) -> dict:
        """
        تعيد الاستراتيجية الآن قاموساً (Dictionary) يمثل إشارة مرشحة (Candidate Signal)
        بدلاً من قرار نهائي.
        """
        previous = market_data.get("rsi_prev")
        current = market_data.get("rsi")
        
        if previous is None or current is None:
            return {"signal": "HOLD"}
            
        # نكتفي برصد التقاطع (Trigger) دون فحص الاتجاه هنا
        if previous < 30 <= current:
            return {
                "signal": "BUY",
                "strategy": self.name,
                "reason": "RSI crossed above 30 (Oversold Reversal)",
                "data": {"rsi": current, "rsi_prev": previous}
            }
            
        if previous > 70 >= current:
            return {
                "signal": "SELL",
                "strategy": self.name,
                "reason": "RSI crossed below 70 (Overbought Reversal)",
                "data": {"rsi": current, "rsi_prev": previous}
            }
            
        return {"signal": "HOLD"}
