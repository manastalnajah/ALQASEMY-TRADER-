from app.strategies.base_strategy import BaseStrategy
from app.strategies.golden_setup import GoldenSetupStrategy
from app.logging.logger import system_logger

class StrategyManager:
    def __init__(self):
        # 🔥 تم تعطيل الاستراتيجيات القديمة لمنع خطأ الـ float(Series)
        # وإبقاء الاستراتيجية الذهبية (الوحيدة المتوافقة مع Pandas)
        self._strategies: dict[str, BaseStrategy] = {
            "golden": GoldenSetupStrategy(),
        }

    def execute(self, strategy_name: str, market_data: dict):
        strategy = self._strategies.get(strategy_name.lower())
        if not strategy:
            system_logger.error("Unknown strategy: %s", strategy_name)
            return {"decision": "HOLD"}
        return strategy.analyze(market_data)


manager = StrategyManager()
