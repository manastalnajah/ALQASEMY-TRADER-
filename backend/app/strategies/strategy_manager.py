from app.strategies.base_strategy import BaseStrategy
from app.strategies.scalping_strategy import ScalpingStrategy
from app.strategies.ma_crossover_strategy import MACrossoverStrategy
from app.strategies.rsi_reversal_strategy import RSIReversalStrategy
from app.strategies.smart_limit_strategy import SmartLimitStrategy
from app.logging.logger import system_logger


class StrategyManager:
    def __init__(self):
        self._strategies: dict[str, BaseStrategy] = {
            "scalping": ScalpingStrategy(),
            "crossover": MACrossoverStrategy(),
            "ma_cross": MACrossoverStrategy(),
            "rsi": RSIReversalStrategy(),
            "smart_limits": SmartLimitStrategy(),
        }

    def execute(self, strategy_name: str, market_data: dict):
        strategy = self._strategies.get(strategy_name.lower())
        if not strategy:
            system_logger.error("Unknown strategy: %s", strategy_name)
            return {"decision": "HOLD"}
        return strategy.analyze(market_data)


manager = StrategyManager()
