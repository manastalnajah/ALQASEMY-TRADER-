from app.strategies.base_strategy import BaseStrategy
from app.strategies.golden_setup import GoldenSetupStrategy
from app.strategies.smart_limit_strategy import SmartLimitStrategy  # 🚀 تم تعديل اسم الملف هنا ليتطابق تماماً
from app.logging.logger import system_logger

class StrategyManager:
    def __init__(self):
        self._strategies: dict[str, BaseStrategy] = {
            "golden": GoldenSetupStrategy(),
            "golden_setup": GoldenSetupStrategy(),
            "smart_limits": SmartLimitStrategy(),
            "smart_limit": SmartLimitStrategy(),
            "smart_support_&_resistance_limits": SmartLimitStrategy()
        }

    def execute(self, strategy_name: str, market_data: dict):
        clean_name = strategy_name.lower().replace(" ", "_")
        
        strategy = self._strategies.get(clean_name)
        if not strategy:
            system_logger.error("Unknown strategy: %s", strategy_name)
            return {"decision": "HOLD"}
            
        return strategy.analyze(market_data)


manager = StrategyManager()
