from app.strategies.base_strategy import BaseStrategy
from app.logging.logger import system_logger

class ScalpingStrategy(BaseStrategy):
    def __init__(self):
        # نحدد اسم الاستراتيجية عند تهيئتها
        super().__init__(name="Scalping 1-Min Trend")

    def analyze(self, market_data: dict) -> str:
        """
        تحليل بيانات السوق (مثل السعر الحالي، والمؤشرات) لاتخاذ قرار فوري.
        """
        system_logger.info(f"🔍 جاري تحليل السوق باستخدام استراتيجية: {self.name}")
        
        # استخراج البيانات القادمة من الميتاتريدر (كمثال)
        current_price = market_data.get("price")
        moving_average = market_data.get("ma_14")

        # إذا كانت البيانات ناقصة، نوقف التداول وننتظر
        if not current_price or not moving_average:
            system_logger.warning("⚠️ بيانات السوق غير مكتملة، القرار: HOLD")
            return "HOLD"

        # خوارزمية التداول (مثال مبسط لتقاطع السعر مع المتوسط المتحرك)
        if current_price > moving_average:
            system_logger.info("📈 إشارة شراء اكتشفت! السعر أعلى من المتوسط.")
            return "BUY"
            
        elif current_price < moving_average:
            system_logger.info("📉 إشارة بيع اكتشفت! السعر أقل من المتوسط.")
            return "SELL"
            
        return "HOLD"