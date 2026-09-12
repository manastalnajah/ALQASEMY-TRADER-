from app.strategies.base_strategy import BaseStrategy


class RSIReversalStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="RSI Mean Reversion")

    def analyze(self, market_data: dict):
        previous = market_data.get("rsi_prev")
        current = market_data.get("rsi")
        if previous is None or current is None:
            return "HOLD"
        bias = market_data.get("market_bias", "NEUTRAL")
        # Entry occurs on a cross back out of an extreme zone, and only in the MTF-confirmed direction.
        if previous < 30 <= current and bias == "BUY":
            return "BUY"
        if previous > 70 >= current and bias == "SELL":
            return "SELL"
        return "HOLD"
