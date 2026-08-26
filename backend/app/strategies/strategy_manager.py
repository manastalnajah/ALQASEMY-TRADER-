from app.strategies.base_strategy import BaseStrategy
from app.strategies.scalping_strategy import ScalpingStrategy
from app.strategies.ma_crossover_strategy import MACrossoverStrategy
from app.strategies.rsi_reversal_strategy import RSIReversalStrategy
from app.logging.logger import system_logger

class StrategyManager:
    """
    هذا هو 'العقل المدبر' الذي يحفظ كل الاستراتيجيات.
    وظيفته استلام اسم الاستراتيجية من تطبيق فلاتر، وتشغيل الكود الخاص بها فوراً.
    """
    def __init__(self):
        # قاموس (Dictionary) يربط كل اسم بالملف الخاص به
        # تمت إضافة الاستراتيجيات الجديدة هنا
        self._strategies: dict[str, BaseStrategy] = {
            "scalping": ScalpingStrategy(),
            "crossover": MACrossoverStrategy(),
            "rsi": RSIReversalStrategy(),
        }

    def execute(self, strategy_name: str, market_data: dict) -> str:
        # 1. البحث عن الاستراتيجية المطلوبة بالاسم
        strategy = self._strategies.get(strategy_name.lower())
        
        # 2. إذا أدخلت اسماً خاطئاً من التطبيق، يمنع الانهيار
        if not strategy:
            system_logger.error(f"❌ الاستراتيجية '{strategy_name}' غير مسجلة في النظام!")
            return "HOLD"
            
        # 3. إذا وجدها، يقوم بتشغيل دالة التحليل الخاصة بها
        system_logger.info(f"⚙️ توجيه البيانات إلى استراتيجية: {strategy.name}")
        return strategy.analyze(market_data)

# إنشاء نسخة واحدة من المدير تعمل على مستوى السيرفر بالكامل
manager = StrategyManager()