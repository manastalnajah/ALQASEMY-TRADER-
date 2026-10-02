import numpy as np
import logging
from typing import List, Dict, Any
from app.services.quant_engine import QuantEngine

logger = logging.getLogger("AlqasemyTrader")

class QuantAnalyzer:
    def __init__(self):
        self.engine = QuantEngine()

    def analyze_single_asset(self, close_prices: List[float]) -> Dict[str, Any]:
        """
        يقوم بتحليل الشموع لزوج واحد (مثل EURUSD) ويعيد تقريراً كمياً مفصلاً
        لاتخاذ قرار الشراء أو البيع أو التوقف.
        """
        if len(close_prices) < 50:
            return {"status": "insufficient_data"}

        # 1. تحويل البيانات إلى مصفوفة Numpy لسرعة المعالجة
        series = np.array(close_prices)

        # 2. هل السوق في ترند أم يرتد؟ (Hurst Exponent)
        hurst = self.engine.calculate_hurst(series)
        market_regime = "TRENDING" if hurst > 0.55 else "MEAN_REVERTING" if hurst < 0.45 else "RANDOM"

        # 3. حساب مدى انحراف السعر (Z-Score) لاصطياد الارتدادات
        z_score = self.engine.calculate_zscore(series)

        # 4. حساب العمر النصف (الزمن المتوقع لنجاح الصفقة)
        _, _, half_life = self.engine.calculate_ou_params(series)

        # 5. اتخاذ القرار المبدئي بناءً على النماذج
        signal = "NEUTRAL"
        if market_regime == "MEAN_REVERTING":
            if z_score > 2.0:
                signal = "SELL" # السعر صعد بشكل غير مبرر إحصائياً، حان وقت البيع
            elif z_score < -2.0:
                signal = "BUY"  # السعر هبط بشكل غير مبرر إحصائياً، حان وقت الشراء

        logger.info(f"📊 Quant Analysis | Regime: {market_regime} (H={hurst:.2f}) | Z-Score: {z_score:.2f} | Signal: {signal}")

        return {
            "status": "success",
            "market_regime": market_regime,
            "hurst_exponent": round(hurst, 3),
            "z_score": round(z_score, 3),
            "estimated_half_life_candles": round(half_life, 1),
            "suggested_signal": signal
        }

    def calculate_dynamic_risk(self, win_rate: float, avg_win: float, avg_loss: float, max_risk_cap: float = 0.05) -> float:
        """
        يحسب المخاطرة كنسبة مئوية من الحساب باستخدام Fractional Kelly.
        """
        kelly = self.engine.calculate_fractional_kelly(win_rate, avg_win, avg_loss)
        # تحديد سقف أعلى للمخاطرة (مثلا لا يتجاوز 5% مهما كانت الإغراءات)
        safe_risk = min(kelly, max_risk_cap)
        return safe_risk
