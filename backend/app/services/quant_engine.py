import numpy as np
import math
from statsmodels.tsa.stattools import coint

class QuantEngine:
    def __init__(self):
        # متغيرات فلتر كالمان (يتم حفظ حالتها لتتبع العلاقة بين الزوجين بمرور الوقت)
        self.beta = 0.0
        self.P = 1.0
        self.Q = 1e-5
        self.R = 1e-3

    def update_kalman(self, price_y: float, price_x: float) -> float:
        """تحديث فلتر كالمان لحساب نسبة التحوط (Beta) بين زوجين"""
        beta_pred = self.beta
        P_pred = self.P + self.Q

        y_pred = beta_pred * price_x
        error = price_y - y_pred
        
        S = (price_x * P_pred * price_x) + self.R
        K = (P_pred * price_x) / S

        self.beta = beta_pred + K * error
        self.P = (1 - K * price_x) * P_pred

        return self.beta

    def check_cointegration(self, series_y: np.ndarray, series_x: np.ndarray, threshold: float = 0.05) -> bool:
        """
        اختبار التكامل المشترك بين زوجين للتأكد من ترابطهما الإحصائي.
        """
        if len(series_y) < 50 or len(series_x) < 50:
            return False
            
        score, p_value, _ = coint(series_y, series_x)
        return p_value < threshold

    def calculate_zscore(self, spread_series: np.ndarray) -> float:
        """
        حساب Z-Score لمعرفة مدى انحراف السعر الحالي عن المتوسط الطبيعي.
        Z-Score > 2 (بيع) | Z-Score < -2 (شراء)
        """
        if len(spread_series) < 20:
            return 0.0
            
        mean = np.mean(spread_series)
        std = np.std(spread_series)
        
        if std == 0:
            return 0.0
            
        current_spread = spread_series[-1]
        z_score = (current_spread - mean) / std
        return z_score

    def calculate_ou_params(self, spread_series: np.ndarray):
        """
        حساب العمر النصف (Half-life) لتوقع متى سيعود السعر لمتوسطه.
        """
        if len(spread_series) < 2:
            return 0.0, 0.0, float('inf')

        x = spread_series[:-1]
        y = spread_series[1:]
        
        b, a = np.polyfit(x, y, 1)

        if b <= 0 or b >= 1:
            return 0.0, 0.0, float('inf')

        theta = -np.log(b)
        mu = a / (1 - b)
        half_life = math.log(2) / theta if theta > 0 else float('inf')

        return theta, mu, half_life

    def calculate_hurst(self, series: np.ndarray, max_lag: int = 20) -> float:
        """
        حساب أس هيرست لتحديد حالة السوق:
        H < 0.5 (سوق يرتد Mean-Reverting)
        H > 0.5 (سوق في ترند Trending)
        """
        if len(series) < max_lag * 2:
            return 0.5 

        lags = range(2, max_lag)
        # حساب التباين للفروق الزمنية
        tau = [np.std(np.subtract(series[lag:], series[:-lag])) for lag in lags]
        
        # تجنب أخطاء القسمة أو اللوغاريتم للصفر
        if any(t == 0 for t in tau):
            return 0.5

        poly = np.polyfit(np.log(lags), np.log(tau), 1)
        return poly[0]

    def calculate_fractional_kelly(self, win_rate: float, avg_win: float, avg_loss: float, fraction: float = 0.5) -> float:
        """
        حساب حجم اللوت الآمن رياضياً لتعظيم الأرباح دون المخاطرة بالإفلاس.
        """
        if avg_loss == 0 or avg_win == 0:
            return 0.0
            
        r = avg_win / abs(avg_loss)
        kelly_pct = (win_rate * r - (1 - win_rate)) / r
        
        # إرجاع النسبة مكسورة (Fractional) لتقليل المخاطرة
        return max(0.0, kelly_pct * fraction)
