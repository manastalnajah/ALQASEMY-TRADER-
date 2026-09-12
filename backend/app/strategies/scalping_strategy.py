from app.strategies.base_strategy import BaseStrategy


class ScalpingStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="Scalping Trend")

    def analyze(self, market_data: dict):
        # Kept for compatibility but disabled by default in production config.
        price = market_data.get("close")
        ma = market_data.get("ma_14")
        prev_price = market_data.get("close_prev")
        prev_ma = market_data.get("ma_14_prev")
        if None in (price, ma, prev_price, prev_ma):
            return "HOLD"
        if prev_price <= prev_ma and price > ma:
            return "BUY"
        if prev_price >= prev_ma and price < ma:
            return "SELL"
        return "HOLD"
