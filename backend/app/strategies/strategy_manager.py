from app.strategies.base_strategy import BaseStrategy
from app.strategies.golden_setup import GoldenSetupStrategy
from app.strategies.smart_limits import SmartLimitStrategy  # 🚀 إضافة استراتيجية الأوامر المعلقة الذكية
from app.logging.logger import system_logger

class StrategyManager:
    def __init__(self):
        # 🔥 تم تسجيل الاستراتيجيات الاحترافية:
        # 1. الذهبية: لاصطياد الاتجاهات القوية (Trend)
        # 2. السمارت ليميت: لاصطياد الارتدادات في التذبذب (Range)
        self._strategies: dict[str, BaseStrategy] = {
            "golden": GoldenSetupStrategy(),
            "golden_setup": GoldenSetupStrategy(),
            "smart_limits": SmartLimitStrategy(),                # 🚀 التسجيل الأساسي
            "smart_limit": SmartLimitStrategy(),                 # اسم مرادف للحماية
            "smart_support_&_resistance_limits": SmartLimitStrategy() # الاسم الداخلي للاستراتيجية
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
