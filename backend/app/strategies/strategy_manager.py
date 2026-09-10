from app.strategies.base_strategy import BaseStrategy
from app.strategies.scalping_strategy import ScalpingStrategy
from app.strategies.ma_crossover_strategy import MACrossoverStrategy
from app.strategies.rsi_reversal_strategy import RSIReversalStrategy
from app.strategies.smart_limit_strategy import SmartLimitStrategy  # 👈 1. استيراد الاستراتيجية الجديدة
from app.logging.logger import system_logger

class StrategyManager:
    """
    هذا هو 'العقل المدبر' الذي يحفظ كل الاستراتيجيات.
    وظيفته استلام اسم الاستراتيجية، وتشغيل الكود الخاص بها فوراً.
    """
    def __init__(self):
        # قاموس (Dictionary) يربط كل اسم بالملف الخاص به
        self._strategies: dict[str, BaseStrategy] = {
            "scalping": ScalpingStrategy(),
            "crossover": MACrossoverStrategy(),
            "ma_cross": MACrossoverStrategy(), 
            "rsi": RSIReversalStrategy(),
            "smart_limits": SmartLimitStrategy(),  # 👈 2. تسجيلها لكي يتعرف عليها mt5_router
        }

    def execute(self, strategy_name: str, market_data: dict):
        # 1. البحث عن الاستراتيجية المطلوبة بالاسم (مع تحويل الحروف إلى صغيرة لتفادي أخطاء الكتابة)
        strategy = self._strategies.get(strategy_name.lower())
        
        # 2. إذا أدخلت اسماً خاطئاً، يمنع الانهيار
        if not strategy:
            system_logger.error(f"❌ الاستراتيجية '{strategy_name}' غير مسجلة في النظام!")
            return {"decision": "HOLD"}  # تدعم القاموس والنص معاً
            
        # 3. إذا وجدها، يقوم بتشغيل دالة التحليل الخاصة بها
        system_logger.info(f"⚙️ توجيه البيانات إلى استراتيجية: {strategy.name}")
        return strategy.analyze(market_data)

# إنشاء نسخة واحدة من المدير تعمل على مستوى السيرفر بالكامل
manager = StrategyManager()
