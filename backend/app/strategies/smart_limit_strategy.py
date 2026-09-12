from app.strategies.base_strategy import BaseStrategy


class SmartLimitStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="Smart Support & Resistance Limits")

    def analyze(self, market_data: dict):
        price = float(market_data.get("close") or 0)
        support = market_data.get("support")
        resistance = market_data.get("resistance")
        point = float(market_data.get("point") or 0)
        if price <= 0 or support is None or resistance is None or point <= 0:
            return {"decision": "HOLD"}

        # Require a meaningful range and use the broker's actual point size.
        if resistance <= support:
            return {"decision": "HOLD"}
        range_points = (resistance - support) / point
        if range_points < 50:
            return {"decision": "HOLD"}

        distance_support = (price - support) / point
        distance_resistance = (resistance - price) / point
        trigger_points = min(50.0, max(10.0, range_points * 0.10))

        if 0 <= distance_support <= trigger_points:
            return {
                "decision": "BUY_LIMIT",
                "entry_price": float(support),
                "sl": float(support - max(point * 10, (resistance - support) * 0.10)),
                "tp": float(support + (resistance - support) * 0.50),
            }
        if 0 <= distance_resistance <= trigger_points:
            return {
                "decision": "SELL_LIMIT",
                "entry_price": float(resistance),
                "sl": float(resistance + max(point * 10, (resistance - support) * 0.10)),
                "tp": float(resistance - (resistance - support) * 0.50),
            }
        return {"decision": "HOLD"}
