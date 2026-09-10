from app.strategies.base_strategy import BaseStrategy
from app.logging.logger import system_logger

class MACrossoverStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="Moving Average Crossover + Trend Filter")

    def analyze(self, market_data: dict) -> str:
        # استخراج المؤشرات
        fast_ma = market_data.get("fast_ma")
        slow_ma = market_data.get("slow_ma")
        current_price = market_data.get("close")

        if not fast_ma or not slow_ma or not current_price:
            system_logger.warning("⚠️ بيانات الشموع غير كافية لقراءة الاتجاه (نحتاج 50 شمعة). القرار: HOLD")
            return "HOLD"

        # ==========================================
        # 🧠 فلتر الاتجاه العام (Macro Trend Filter)
        # ==========================================
        # السعر فوق متوسط 50 = ترند صاعد / السعر تحت متوسط 50 = ترند هابط
        is_uptrend = current_price > slow_ma
        is_downtrend = current_price < slow_ma

        # ==========================================
        # 🎯 اتخاذ القرار مع احترام الاتجاه
        # ==========================================
        # شراء فقط إذا كان الترند صاعداً + حدث تقاطع إيجابي
        if fast_ma > slow_ma and is_uptrend:
            system_logger.info("📈 [ترند صاعد] + تقاطع ذهبي للـ MA -> قرار: BUY")
            return "BUY"
            
        # بيع فقط إذا كان الترند هابطاً + حدث تقاطع سلبي
        elif fast_ma < slow_ma and is_downtrend:
            system_logger.info("📉 [ترند هابط] + تقاطع ميت للـ MA -> قرار: SELL")
            return "SELL"
            
        else:
            # إذا كان هناك تقاطع صاعد لكن الترند هابط (فخ تصحيحي)، سيتجاهله!
            return "HOLD"
