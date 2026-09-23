from app.strategies.base_strategy import BaseStrategy
from app.strategies.golden_setup import GoldenSetupStrategy
from app.logging.logger import system_logger

class StrategyManager:
    def __init__(self):
        # 🔥 تم تعطيل الاستراتيجيات القديمة لمنع خطأ الـ float(Series)
        # وإبقاء الاستراتيجية الذهبية مع تسجيلها بعدة أسماء مرادفة لضمان التوافق المطلق
        self._strategies: dict[str, BaseStrategy] = {
            "golden": GoldenSetupStrategy(),
            "golden_setup": GoldenSetupStrategy(),
        }

    def execute(self, strategy_name: str, market_data: dict):
        # تنظيف الاسم من المسافات وتحويله لأحرف صغيرة لتجنب أي أخطاء مطبعية
        clean_name = strategy_name.lower().replace(" ", "_")
        
        strategy = self._strategies.get(clean_name)
        if not strategy:
            system_logger.error("Unknown strategy: %s", strategy_name)
            return {"decision": "HOLD"}
            
        return strategy.analyze(market_data)


manager = StrategyManager()
