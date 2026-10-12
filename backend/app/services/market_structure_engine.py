market_st# app/services/market_structure_engine.py
import logging

logger = logging.getLogger("AlqasemyTrader")

class MarketStructureEngine:
    def __init__(self, quant_analyzer):
        self.quant = quant_analyzer

    def analyze_structure(self, candles_h1: list, candles_m15: list) -> dict:
        """
        يحلل بنية السوق بناءً على القمم والقيعان واستخراج الكسر (BOS/CHoCH).
        (هذا نموذج مبسط لكيفية بناء المنطق)
        """
        if len(candles_h1) < 20 or len(candles_m15) < 20:
            return {"trend_h1": "UNKNOWN", "structure_m15": "UNKNOWN"}

        # 1. تحديد سياق H1 (مثال مبسط يعتمد على إغلاقات آخر 20 شمعة)
        h1_closes = [c['close'] for c in candles_h1[-20:]]
        if h1_closes[-1] > max(h1_closes[:-5]):
            trend_h1 = "TREND_UP"
        elif h1_closes[-1] < min(h1_closes[:-5]):
            trend_h1 = "TREND_DOWN"
        else:
            trend_h1 = "RANGE"

        # 2. فحص بنية M15 (BOS / CHoCH)
        # هنا يتم برمجياً استخراج الـ HH, HL, LH, LL
        # لأغراض التوضيح، سنعتمد على مقارنة القمم والقيعان المحلية لآخر 5 شموع
        m15_highs = [c['high'] for c in candles_m15[-5:]]
        m15_lows = [c['low'] for c in candles_m15[-5:]]
        
        is_bullish_structure = m15_lows[-1] > m15_lows[0] and m15_highs[-1] > m15_highs[0]
        is_bearish_structure = m15_highs[-1] < m15_highs[0] and m15_lows[-1] < m15_lows[0]

        structure_m15 = "BULLISH" if is_bullish_structure else ("BEARISH" if is_bearish_structure else "CONSOLIDATION")

        return {
            "trend_h1": trend_h1,
            "structure_m15": structure_m15
        }

    def evaluate_candidate(self, candidate: dict, market_context: dict, quant_report: dict) -> dict:
        """
        تتخذ القرار النهائي بمرور أو رفض الصفقة المرشحة.
        """
        signal = candidate.get("signal")
        if signal not in ["BUY", "SELL"]:
            return {"approved": False, "reason": "No valid signal"}

        trend_h1 = market_context.get("trend_h1")
        struct_m15 = market_context.get("structure_m15")
        market_regime = quant_report.get("market_regime")

        # 1. الشروط الإلزامية لتأكيد الاتجاه والبنية
        if signal == "BUY":
            # لا تشتري إذا كان الاتجاه العام هابطاً وبنية M15 هابطة (استمرار هبوطي قوي)
            if trend_h1 == "TREND_DOWN" and struct_m15 == "BEARISH":
                logger.warning("🚫 MSCE Rejected BUY: Strong bearish continuation structure.")
                return {"approved": False, "reason": "Against strong bearish structure"}
                
        elif signal == "SELL":
            # لا تبع إذا كان الاتجاه صاعداً وبنية M15 صاعدة
            if trend_h1 == "TREND_UP" and struct_m15 == "BULLISH":
                logger.warning("🚫 MSCE Rejected SELL: Strong bullish continuation structure.")
                return {"approved": False, "reason": "Against strong bullish structure"}

        # 2. شروط تقييم الجودة (Quant Analyzer)
        # إذا كان السوق Trending بشكل قوي جداً، تجنب التداول العكسي (Mean Reversion)
        if candidate.get("strategy") == "RSI Mean Reversion":
            if market_regime == "TRENDING":
                logger.warning(f"🚫 MSCE Rejected {signal}: RSI Reversion is invalid in a TRENDING regime.")
                return {"approved": False, "reason": "Quant regime is TRENDING (avoid reversion)"}

        # إذا اجتازت الإشارة كل الدفاعات
        logger.info(f"✅ MSCE Approved {signal} from {candidate.get('strategy')}")
        return {"approved": True, "reason": "Structure aligned with signal"}
