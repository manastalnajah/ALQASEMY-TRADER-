# app/services/market_structure_engine.py

import logging
from typing import List, Dict, Optional

logger = logging.getLogger("AlqasemyTrader.MSCE")

class MarketStructureEngine:
    def __init__(self, quant_analyzer=None):
        self.quant = quant_analyzer

    def _find_swings(self, candles: List[Dict], left: int = 3, right: int = 3) -> Dict:
        """
        استخراج القمم والقيعان المحورية (Swing Points) بصرامة.
        زيادة left/right إلى 3 لتقليل الضوضاء وتأكيد المحاور.
        """
        swing_highs = []
        swing_lows = []
        
        # حماية صارمة ضد الـ Look-ahead bias
        for i in range(left, len(candles) - right):
            current_high = candles[i]['high']
            current_low = candles[i]['low']
            
            is_sh = True
            is_sl = True
            
            for j in range(i - left, i + right + 1):
                if i != j:
                    if candles[j]['high'] >= current_high: is_sh = False
                    if candles[j]['low'] <= current_low: is_sl = False
                    
            if is_sh: swing_highs.append({"index": i, "price": current_high, "candle": candles[i]})
            if is_sl: swing_lows.append({"index": i, "price": current_low, "candle": candles[i]})
            
        return {"highs": swing_highs, "lows": swing_lows}

    def _analyze_timeframe_structure(self, candles: List[Dict], name: str) -> Dict:
        """
        تحليل البنية التسلسلي (Sequential Structure Analysis).
        يمسح التاريخ لتحديد السياق الحالي (BOS, CHoCH, Trend).
        """
        if len(candles) < 30:
            return {"trend": "UNKNOWN", "bos": "NONE", "choch": "NONE", "structure": "UNKNOWN"}

        swings = self._find_swings(candles, left=3, right=3)
        highs = swings["highs"]
        lows = swings["lows"]

        if len(highs) < 2 or len(lows) < 2:
            return {"trend": "RANGE", "bos": "NONE", "choch": "NONE", "structure": "CONSOLIDATION"}

        # تتبع تطور البنية
        last_high = highs[-1]
        prev_high = highs[-2]
        last_low = lows[-1]
        prev_low = lows[-2]

        hh = last_high['price'] > prev_high['price']
        lh = last_high['price'] < prev_high['price']
        hl = last_low['price'] > prev_low['price']
        ll = last_low['price'] < prev_low['price']

        # تحديد البنية العامة المستمرة (Swing Structure)
        structure = "RANGE"
        if hh and hl: structure = "BULLISH"
        elif lh and ll: structure = "BEARISH"
        
        # ----------------------------------------------------
        # اكتشاف الـ Break of Structure (BOS) و Change of Character (CHoCH)
        # بالاعتماد على إغلاقات الشموع الأخيرة بعد آخر قمة/قاع
        # ----------------------------------------------------
        bos = "NONE"
        choch = "NONE"
        trend_status = "NEUTRAL"
        
        # نأخذ آخر 5 شموع مغلقة لفحص الاختراقات القريبة
        recent_closes = [c['close'] for c in candles[-5:]]
        max_recent_close = max(recent_closes)
        min_recent_close = min(recent_closes)

        # 1. تحليل الاختراق الصاعد
        if max_recent_close > last_high['price']:
            if structure == "BULLISH":
                bos = "BULLISH_BOS" # استمرار صعود
                trend_status = "TREND_UP"
            elif structure == "BEARISH":
                choch = "BULLISH_CHOCH" # أول علامة انعكاس لأعلى
                trend_status = "TRANSITION_UP"
                
        # 2. تحليل الاختراق الهابط
        elif min_recent_close < last_low['price']:
            if structure == "BEARISH":
                bos = "BEARISH_BOS" # استمرار هبوط
                trend_status = "TREND_DOWN"
            elif structure == "BULLISH":
                choch = "BEARISH_CHOCH" # أول علامة انعكاس لأسفل
                trend_status = "TRANSITION_DOWN"

        # إذا لم يكن هناك كسر حديث، نعتمد على البنية الأساسية
        if trend_status == "NEUTRAL":
            if structure == "BULLISH": trend_status = "TREND_UP"
            elif structure == "BEARISH": trend_status = "TREND_DOWN"
            else: trend_status = "RANGE"

        return {
            "trend": trend_status, 
            "structure": structure, 
            "bos": bos, 
            "choch": choch,
            "last_high": last_high['price'], 
            "last_low": last_low['price']
        }

    def analyze_structure(self, candles_h1: List[Dict], candles_m15: List[Dict], candles_m5: List[Dict]) -> Dict:
        return {
            "H1": self._analyze_timeframe_structure(candles_h1, "H1"),
            "M15": self._analyze_timeframe_structure(candles_m15, "M15"),
            "M5": self._analyze_timeframe_structure(candles_m5, "M5")
        }

    def evaluate_candidate(self, candidate_signal: Dict, structure: Dict, quant_report: Dict) -> Dict:
        """
        بوابة العبور الاحترافية.
        تقييم الإشارة بناءً على التوافق بين الأطر الثلاثة، والتمييز بين الارتداد والاستمرار.
        """
        signal = str(candidate_signal.get("signal", "")).upper()
        if signal not in ["BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"]:
            return {"approved": False, "reason": f"Invalid signal: {signal}"}

        is_buy = signal.startswith("BUY")
        is_sell = signal.startswith("SELL")
        
        h1 = structure["H1"]
        m15 = structure["M15"]
        m5 = structure["M5"]

        # ========================================================
        # 1. شروط الرفض القطعي (Hard Rejections - Default Deny)
        # ========================================================
        if is_buy:
            # الترند العام هابط والبنية على M15 مستمرة في الهبوط (لا BOS ولا CHoCH صاعد)
            if h1["trend"] in ["TREND_DOWN", "TRANSITION_DOWN"] and m15["trend"] == "TREND_DOWN":
                if m15["choch"] != "BULLISH_CHOCH" and m5["choch"] != "BULLISH_CHOCH":
                    return {"approved": False, "reason": "BUY rejected: Strong H1/M15 Bearish flow with no Bullish CHoCH."}
            
            # M5 يكسر قيعان للتو (لا تشتري السكين الساقطة)
            if m5["bos"] == "BEARISH_BOS" or m5["choch"] == "BEARISH_CHOCH":
                return {"approved": False, "reason": "BUY rejected: M5 is actively breaking structure downwards."}

        if is_sell:
            # الترند العام صاعد والبنية على M15 مستمرة في الصعود (لا BOS ولا CHoCH هابط)
            if h1["trend"] in ["TREND_UP", "TRANSITION_UP"] and m15["trend"] == "TREND_UP":
                if m15["choch"] != "BEARISH_CHOCH" and m5["choch"] != "BEARISH_CHOCH":
                    return {"approved": False, "reason": "SELL rejected: Strong H1/M15 Bullish flow with no Bearish CHoCH."}

            # M5 يكسر قمم للتو (لا تبع في وجه صعود حاد)
            if m5["bos"] == "BULLISH_BOS" or m5["choch"] == "BULLISH_CHOCH":
                return {"approved": False, "reason": "SELL rejected: M5 is actively breaking structure upwards."}

        # ========================================================
        # 2. شروط الموافقة (Approval Criteria)
        # يجب إثبات الدافع للدخول
        # ========================================================
        if is_buy:
            # 1. الاستمرار مع الترند: H1 صاعد، و M15 يؤكد
            if h1["trend"] == "TREND_UP" and m15["trend"] in ["TREND_UP", "RANGE"]:
                return {"approved": True, "reason": "BUY approved: Trend Continuation (H1/M15 aligned)."}
            
            # 2. صيد الانعكاس المؤكد: سياق هابط لكن M15 و M5 كسرا لأعلى (CHoCH)
            if m15["choch"] == "BULLISH_CHOCH" and m5["trend"] in ["TREND_UP", "TRANSITION_UP"]:
                return {"approved": True, "reason": "BUY approved: Bullish CHoCH confirmed on M15 & M5."}

        if is_sell:
            # 1. الاستمرار مع الترند: H1 هابط، و M15 يؤكد
            if h1["trend"] == "TREND_DOWN" and m15["trend"] in ["TREND_DOWN", "RANGE"]:
                return {"approved": True, "reason": "SELL approved: Trend Continuation (H1/M15 aligned)."}
            
            # 2. صيد الانعكاس المؤكد: سياق صاعد لكن M15 و M5 كسرا لأسفل (CHoCH)
            if m15["choch"] == "BEARISH_CHOCH" and m5["trend"] in ["TREND_DOWN", "TRANSITION_DOWN"]:
                return {"approved": True, "reason": "SELL approved: Bearish CHoCH confirmed on M15 & M5."}

        # لا توجد أدلة صريحة
        return {"approved": False, "reason": "NO_TRADE: Lack of compelling multi-timeframe structural evidence."}

    def evaluate_open_position(self, position_side: str, structure: Dict, quant_report: Dict) -> Dict:
        """
        إدارة الصفقات النشطة (Active Trade Management - Bailout).
        تقييم ما إذا كان الانعكاس الحالي هو كسر حقيقي يستدعي قطع الخسارة مبكراً.
        """
        trend_h1 = structure["H1"]["trend"]
        struct_m15 = structure["M15"]["trend"]
        choch_m15 = structure["M15"]["choch"]
        
        position_side = str(position_side).upper()

        if position_side == "BUY":
            # خروج طوارئ: H1 أصبح هابطاً، و M15 قام بكسر قاع محوري قوي (CHoCH هابط أو استمرار هبوطي)
            if trend_h1 in ["TREND_DOWN", "TRANSITION_DOWN"] and (struct_m15 == "TREND_DOWN" or choch_m15 == "BEARISH_CHOCH"):
                return {"action": "CLOSE", "reason": "MSCE Bailout: Total Bearish Reversal. Structure broken downwards against BUY."}
        
        elif position_side == "SELL":
            # خروج طوارئ: H1 أصبح صاعداً، و M15 قام بكسر قمة محورية قوية (CHoCH صاعد أو استمرار صعودي)
            if trend_h1 in ["TREND_UP", "TRANSITION_UP"] and (struct_m15 == "TREND_UP" or choch_m15 == "BULLISH_CHOCH"):
                return {"action": "CLOSE", "reason": "MSCE Bailout: Total Bullish Reversal. Structure broken upwards against SELL."}

        return {"action": "HOLD", "reason": "Structure supports current position."}
