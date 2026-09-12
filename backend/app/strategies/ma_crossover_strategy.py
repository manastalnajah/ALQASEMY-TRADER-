from app.strategies.base_strategy import BaseStrategy


class MACrossoverStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="Moving Average Crossover + Trend Filter")

    def analyze(self, market_data: dict):
        fast_prev = market_data.get("fast_ma_prev")
        slow_prev = market_data.get("slow_ma_prev")
        fast = market_data.get("fast_ma")
        slow = market_data.get("slow_ma")
        price = market_data.get("close")
        bias = market_data.get("market_bias", "NEUTRAL")
        if None in (fast_prev, slow_prev, fast, slow, price):
            return "HOLD"

        bullish_cross = fast_prev <= slow_prev and fast > slow
        bearish_cross = fast_prev >= slow_prev and fast < slow
        if bullish_cross and price > slow and bias == "BUY":
            return "BUY"
        if bearish_cross and price < slow and bias == "SELL":
            return "SELL"
        return "HOLD"
