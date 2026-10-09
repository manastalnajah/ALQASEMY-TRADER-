# ============================================================
# app/services/position_risk_analyzer.py
# محلل مخاطر الصفقات المفتوحة
# ------------------------------------------------------------
# المسؤوليات:
# 1. تحليل حالة صفقة مفتوحة (TP progress, R, peak R)
# 2. استدعاء QuantAnalyzer للحصول على سياق السوق
# 3. حساب RSI و EMA محليًا من الشموع
# 4. حساب reversal_score من عدة عوامل
# 5. إرجاع توصية: HOLD / TIGHTEN_SL / CLOSE / PARTIAL_CLOSE
#
# ⚠️ هذا الملف لا ينشئ أوامر إدارة.
#    هو فقط يحلل ويعيد التوصية.
#    PositionManager هو من يتخذ القرار النهائي.
# ============================================================

import logging
from typing import Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.schemas import PositionRiskAnalysis
from app.services.quant_analyzer import QuantAnalyzer


logger = logging.getLogger("AlqasemyTrader.PositionRiskAnalyzer")


# ============================================================
# ثوابت
# ============================================================

# عدد الشموع المطلوبة للتحليل
MIN_CANDLES_REQUIRED = 60

# فترات المؤشرات الافتراضية
DEFAULT_RSI_PERIOD = 14
DEFAULT_EMA_PERIOD = 20

# أوزان عوامل الانعكاس (مجموعها = 100)
REVERSAL_WEIGHTS = {
    "rsi_extreme": 25,       # RSI في منطقة تشبع
    "rsi_weakening": 15,     # RSI يفقد قوته
    "price_vs_ema": 20,      # السعر مقابل EMA
    "candle_structure": 15,  # بنية الشمعة الأخيرة
    "momentum_shift": 15,    # تغير الزخم
    "quant_regime": 10,      # تأكيد من QuantAnalyzer
}


# ============================================================
# دوال حسابية داخلية
# ============================================================

def _calculate_rsi(prices: list[float], period: int = DEFAULT_RSI_PERIOD) -> float:
    """
    حساب RSI من قائمة أسعار الإغلاق.

    يعيد 50.0 عند عدم كفاية البيانات.
    """
    if not prices or len(prices) < period + 1:
        return 50.0

    gains = []
    losses = []

    for i in range(1, len(prices)):
        change = prices[i] - prices[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(change))

    if len(gains) < period:
        return 50.0

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _calculate_ema(prices: list[float], period: int = DEFAULT_EMA_PERIOD) -> Optional[float]:
    """
    حساب EMA من قائمة أسعار الإغلاق.

    يعيد None عند عدم كفاية البيانات.
    """
    if not prices or len(prices) < period:
        return None

    multiplier = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period

    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema

    return ema


def _safe_float(value, default: float = 0.0) -> float:
    """تحويل آمن إلى float."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ============================================================
# المحلل الرئيسي
# ============================================================

class PositionRiskAnalyzer:
    """
    محلل مخاطر صفقة مفتوحة.

    الاستخدام:
        analyzer = PositionRiskAnalyzer(db)
        analysis = await analyzer.analyze(
            position_ticket=123456,
            symbol="XAUUSD",
            side="BUY",
            entry_price=2650.0,
            current_price=2660.0,
            take_profit=2670.0,
            stop_loss=2640.0,
            initial_risk=100.0,
            peak_profit=60.0,
            current_profit=40.0,
        )
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.quant = QuantAnalyzer()

    # ============================================================
    # الدالة الرئيسية
    # ============================================================

    async def analyze(
        self,
        *,
        position_ticket: int,
        symbol: str,
        side: str,             # BUY / SELL
        entry_price: float,
        current_price: float,
        take_profit: float,
        stop_loss: float,
        initial_risk: float,
        peak_profit: float,
        current_profit: float,
        timeframe: str = "M15",
        rsi_period: int = DEFAULT_RSI_PERIOD,
        ema_period: int = DEFAULT_EMA_PERIOD,
    ) -> PositionRiskAnalysis:
        """
        تحليل شامل لصفقة مفتوحة.

        يعيد PositionRiskAnalysis مع:
        - tp_progress
        - current_r / peak_r
        - market_regime / hurst / z_score (من QuantAnalyzer)
        - rsi
        - momentum_weakening
        - reversal_score
        - recommended_action
        """

        # --------------------------------------------------------
        # 1. حسابات R و TP progress
        # --------------------------------------------------------
        tp_progress = self._calculate_tp_progress(
            side=side,
            entry=entry_price,
            current=current_price,
            tp=take_profit,
        )

        current_r = 0.0
        peak_r = 0.0

        if initial_risk and initial_risk > 0:
            current_r = current_profit / initial_risk
            peak_r = peak_profit / initial_risk

        # --------------------------------------------------------
        # 2. جلب الشموع
        # --------------------------------------------------------
        candles = await self._fetch_candles(symbol, timeframe)
        close_prices = [c["close"] for c in candles] if candles else []

        # --------------------------------------------------------
        # 3. حساب RSI و EMA محليًا
        # --------------------------------------------------------
        rsi_value = _calculate_rsi(close_prices, rsi_period) if close_prices else 50.0
        ema_value = _calculate_ema(close_prices, ema_period) if close_prices else None

        # --------------------------------------------------------
        # 4. QuantAnalyzer (سياق السوق)
        # --------------------------------------------------------
        quant_report = {}
        if len(close_prices) >= 50:
            try:
                quant_report = self.quant.analyze_single_asset(close_prices) or {}
            except Exception as exc:
                logger.warning("QuantAnalyzer failed: %s", exc)
                quant_report = {}

        market_regime = quant_report.get("market_regime")
        hurst = quant_report.get("hurst_exponent")
        z_score = quant_report.get("z_score")

        # --------------------------------------------------------
        # 5. كشف ضعف الزخم
        # --------------------------------------------------------
        momentum_weakening = self._detect_momentum_weakening(
            side=side,
            rsi=rsi_value,
            current_price=current_price,
            ema_value=ema_value,
            candles=candles,
        )

        # --------------------------------------------------------
        # 6. حساب reversal_score
        # --------------------------------------------------------
        reversal_score = self._calculate_reversal_score(
            side=side,
            rsi=rsi_value,
            current_price=current_price,
            ema_value=ema_value,
            candles=candles,
            market_regime=market_regime,
        )

        # --------------------------------------------------------
        # 7. التوصية
        # --------------------------------------------------------
        recommended_action, reason = self._decide_action(
            side=side,
            tp_progress=tp_progress,
            current_r=current_r,
            peak_r=peak_r,
            reversal_score=reversal_score,
            momentum_weakening=momentum_weakening,
            rsi=rsi_value,
        )

        return PositionRiskAnalysis(
            position_ticket=position_ticket,
            symbol=symbol,
            tp_progress=tp_progress,
            current_r=current_r,
            peak_r=peak_r,
            market_regime=market_regime,
            hurst_exponent=hurst,
            z_score=z_score,
            rsi=rsi_value,
            momentum_weakening=momentum_weakening,
            reversal_score=reversal_score,
            recommended_action=recommended_action,
            reason=reason,
        )

    # ============================================================
    # الحسابات الفرعية
    # ============================================================

    @staticmethod
    def _calculate_tp_progress(
        *,
        side: str,
        entry: float,
        current: float,
        tp: float,
    ) -> float:
        """
        حساب نسبة التقدم نحو TP.

        - 0.0 = عند الدخول
        - 1.0 = عند TP
        - إذا تحرك السعر عكس الصفقة، تعود 0.0
        """
        if tp <= 0 or entry <= 0:
            return 0.0

        side = (side or "").upper()

        if side == "BUY":
            total = tp - entry
            moved = current - entry
        elif side == "SELL":
            total = entry - tp
            moved = entry - current
        else:
            return 0.0

        if total <= 0:
            return 0.0

        progress = moved / total
        # نقصّ عند 0 إذا تحرك السعر عكس الصفقة
        return max(0.0, min(1.0, progress))

    async def _fetch_candles(
        self,
        symbol: str,
        timeframe: str,
    ) -> list[dict]:
        """
        جلب آخر N شمعة من قاعدة البيانات.

        ⚠️ مهم: PostgreSQL NUMERIC يُرجع decimal.Decimal في Python.
        نحول كل القيم الرقمية إلى float لتفادي أخطاء:
            TypeError: unsupported operand type(s) for +: 'Decimal' and 'float'
        """
        try:
            query = text("""
                SELECT open_time, open, high, low, close, volume
                FROM candles
                WHERE symbol_name = :sym
                  AND timeframe = :tf
                  AND is_closed = true
                ORDER BY open_time DESC
                LIMIT 200
            """)
            result = await self.db.execute(
                query,
                {"sym": symbol.upper(), "tf": timeframe.upper()},
            )
            rows = result.mappings().all()

            # ✅ تحويل صريح إلى float/int
            candles = []
            for r in rows:
                candles.append({
                    "open_time": r["open_time"],
                    "open": _safe_float(r["open"]),
                    "high": _safe_float(r["high"]),
                    "low": _safe_float(r["low"]),
                    "close": _safe_float(r["close"]),
                    "volume": int(r["volume"]) if r["volume"] is not None else 0,
                })

            # ترتيب تصاعدي (الأقدم أولًا)
            return candles[::-1]

        except Exception as exc:
            logger.warning(
                "Failed to fetch candles for %s %s: %s",
                symbol, timeframe, exc,
            )
            return []
    @staticmethod
    def _detect_momentum_weakening(
        *,
        side: str,
        rsi: float,
        current_price: float,
        ema_value: Optional[float],
        candles: list[dict],
    ) -> bool:
        """
        كشف ضعف الزخم.

        - BUY: RSI > 65 وبدأ ينخفض، أو السعر كسر EMA لأسفل،
               أو آخر شمعة حمراء بعد شمعة خضراء.
        - SELL: العكس.
        """
        side = (side or "").upper()

        if len(candles) < 3:
            return False

        last = candles[-1]
        prev = candles[-2]

        try:
            last_close = float(last["close"])
            last_open = float(last["open"])
            prev_close = float(prev["close"])
        except (KeyError, TypeError, ValueError):
            return False

        if side == "BUY":
            # RSI مرتفع وبدأ ينخفض
            if rsi >= 65 and rsi < 72:
                # نتحقق من انخفاض آخر سعر
                if last_close < prev_close:
                    return True

            # كسر EMA لأسفل
            if ema_value is not None and last_close < ema_value:
                return True

            # شمعة حمراء بعد شمعة خضراء
            if last_close < last_open and prev_close > float(prev["open"]):
                return True

        elif side == "SELL":
            # RSI منخفض وبدأ يرتفع
            if rsi <= 35 and rsi > 28:
                if last_close > prev_close:
                    return True

            # كسر EMA لأعلى
            if ema_value is not None and last_close > ema_value:
                return True

            # شمعة خضراء بعد شمعة حمراء
            if last_close > last_open and prev_close < float(prev["open"]):
                return True

        return False

    @staticmethod
    def _calculate_reversal_score(
        *,
        side: str,
        rsi: float,
        current_price: float,
        ema_value: Optional[float],
        candles: list[dict],
        market_regime: Optional[str],
    ) -> int:
        """
        حساب درجة الانعكاس (0-100) من عدة عوامل مرجّحة.

        ملاحظة: هذه درجة استدلالية وليست احتمالًا إحصائيًا.
        """
        if len(candles) < 3:
            return 0

        side = (side or "").upper()
        score = 0

        last = candles[-1]
        prev = candles[-2]

        try:
            last_close = float(last["close"])
            last_open = float(last["open"])
            last_high = float(last["high"])
            last_low = float(last["low"])
            prev_close = float(prev["close"])
        except (KeyError, TypeError, ValueError):
            return 0

        # ----------------------------------------------------
        # 1. RSI في منطقة تشبع
        # ----------------------------------------------------
        if side == "BUY":
            if rsi >= 75:
                score += REVERSAL_WEIGHTS["rsi_extreme"]
            elif rsi >= 70:
                score += REVERSAL_WEIGHTS["rsi_extreme"] * 0.6
            elif rsi >= 65:
                score += REVERSAL_WEIGHTS["rsi_extreme"] * 0.3
        elif side == "SELL":
            if rsi <= 25:
                score += REVERSAL_WEIGHTS["rsi_extreme"]
            elif rsi <= 30:
                score += REVERSAL_WEIGHTS["rsi_extreme"] * 0.6
            elif rsi <= 35:
                score += REVERSAL_WEIGHTS["rsi_extreme"] * 0.3

        # ----------------------------------------------------
        # 2. RSI يفقد قوته
        # ----------------------------------------------------
        if side == "BUY":
            if rsi < 60 and rsi > 45:
                score += REVERSAL_WEIGHTS["rsi_weakening"] * 0.5
        elif side == "SELL":
            if rsi > 40 and rsi < 55:
                score += REVERSAL_WEIGHTS["rsi_weakening"] * 0.5

        # ----------------------------------------------------
        # 3. السعر مقابل EMA
        # ----------------------------------------------------
        if ema_value is not None:
            if side == "BUY" and last_close < ema_value:
                score += REVERSAL_WEIGHTS["price_vs_ema"]
            elif side == "SELL" and last_close > ema_value:
                score += REVERSAL_WEIGHTS["price_vs_ema"]

        # ----------------------------------------------------
        # 4. بنية الشمعة الأخيرة
        # ----------------------------------------------------
        candle_range = last_high - last_low
        if candle_range > 0:
            if side == "BUY":
                # شمعة حمراء قوية
                if last_close < last_open:
                    body = last_open - last_close
                    if body / candle_range >= 0.6:
                        score += REVERSAL_WEIGHTS["candle_structure"]
                    else:
                        score += REVERSAL_WEIGHTS["candle_structure"] * 0.4

                # شمعة بظل علوي طويل
                upper_wick = last_high - max(last_open, last_close)
                if upper_wick / candle_range >= 0.5:
                    score += REVERSAL_WEIGHTS["candle_structure"] * 0.5

            elif side == "SELL":
                # شمعة خضراء قوية
                if last_close > last_open:
                    body = last_close - last_open
                    if body / candle_range >= 0.6:
                        score += REVERSAL_WEIGHTS["candle_structure"]
                    else:
                        score += REVERSAL_WEIGHTS["candle_structure"] * 0.4

                # شمعة بظل سفلي طويل
                lower_wick = min(last_open, last_close) - last_low
                if lower_wick / candle_range >= 0.5:
                    score += REVERSAL_WEIGHTS["candle_structure"] * 0.5

        # ----------------------------------------------------
        # 5. تغير الزخم
        # ----------------------------------------------------
        if side == "BUY":
            if last_close < prev_close:
                score += REVERSAL_WEIGHTS["momentum_shift"]
        elif side == "SELL":
            if last_close > prev_close:
                score += REVERSAL_WEIGHTS["momentum_shift"]

        # ----------------------------------------------------
        # 6. تأكيد من QuantAnalyzer
        # ----------------------------------------------------
        if market_regime == "MEAN_REVERTING":
            # سوق يميل للارتداد — عامل مساعد للانعكاس
            score += REVERSAL_WEIGHTS["quant_regime"] * 0.5
        elif market_regime == "TRENDING":
            # سوق اتجاهي — عامل معاكس للانعكاس
            score -= REVERSAL_WEIGHTS["quant_regime"] * 0.5

        # حد أعلى وأدنى
        return int(max(0, min(100, score)))

    @staticmethod
    def _decide_action(
        *,
        side: str,
        tp_progress: float,
        current_r: float,
        peak_r: float,
        reversal_score: int,
        momentum_weakening: bool,
        rsi: float,
    ) -> tuple[Optional[str], str]:
        """
        اتخاذ القرار النهائي بناءً على كل العوامل.

        القواعد (من الأكثر تحفظًا إلى الأقل):
        1. إغلاق كامل:    reversal_score >= 80 و tp_progress >= 0.7
        2. تقريب SL:     reversal_score >= 60 و tp_progress >= 0.5
        3. إغلاق جزئي:   reversal_score >= 70 و tp_progress >= 0.8
        4. HOLD:         خلاف ذلك
        """
        side = (side or "").upper()

        # ----------------------------------------------------
        # 1. إغلاق كامل عند انعكاس قوي مع تقدم كبير
        # ----------------------------------------------------
        if reversal_score >= 80 and tp_progress >= 0.7:
            return (
                "CLOSE_POSITION",
                f"Reversal score {reversal_score} with TP progress {tp_progress:.0%}",
            )

        # ----------------------------------------------------
        # 2. إغلاق جزئي عند انعكاس قوي جدًا مع ربح كبير
        # ----------------------------------------------------
        if reversal_score >= 70 and tp_progress >= 0.8 and peak_r >= 1.0:
            return (
                "PARTIAL_CLOSE",
                f"Strong reversal {reversal_score} near TP with peak {peak_r:.2f}R",
            )

        # ----------------------------------------------------
        # 3. تقريب SL عند انعكاس متوسط
        # ----------------------------------------------------
        if reversal_score >= 60 and tp_progress >= 0.5:
            return (
                "MODIFY_SL_TP",
                f"Reversal score {reversal_score} with TP progress {tp_progress:.0%}",
            )

        # ----------------------------------------------------
        # 4. تقريب SL عند ضعف زخم مع ربح محقق
        # ----------------------------------------------------
        if momentum_weakening and current_r >= 0.8 and tp_progress >= 0.4:
            return (
                "MODIFY_SL_TP",
                f"Momentum weakening at {current_r:.2f}R",
            )

        # ----------------------------------------------------
        # 5. لا إجراء
        # ----------------------------------------------------
        return (None, "")
