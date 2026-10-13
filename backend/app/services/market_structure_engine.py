# app/services/market_structure_engine.py

import logging
from typing import List, Dict

logger = logging.getLogger("AlqasemyTrader.MSCE")

class MarketStructureEngine:
    def __init__(self, quant_analyzer=None):
        self.quant = quant_analyzer

    def _find_swings(self, candles: List[Dict], left: int = 2, right: int = 2) -> Dict:
        """
        استخراج القمم والقيعان (Fractals).
        التقليل إلى 2 يعطي مرونة ممتازة لالتقاط الهيكل الحقيقي للسوق دون تأخير كبير.
        """
        swing_highs = []
        swing_lows = []
        
        for i in range(left, len(candles) - right):
            current_high = candles[i]['high']
            current_low = candles[i]['low']
            
            is_sh = True
            is_sl = True
            
            for j in range(i - left, i + right + 1):
                if i != j:
                    if candles[j]['high'] > current_high: is_sh = False
                    if candles[j]['low'] < current_low: is_sl = False
                    
            if is_sh: swing_highs.append({"index": i, "price": current_high})
            if is_sl: swing_lows.append({"index": i, "price": current_low})
            
        return {"highs": swing_highs, "lows": swing_lows}

    def _analyze_timeframe_structure(self, candles: List[Dict], name: str) -> Dict:
        """يحلل البنية ويمسح التاريخ لتحديد السياق الحالي."""
        if len(candles) < 20:
            return {"trend": "UNKNOWN", "bos": "NONE", "choch": "NONE", "structure": "UNKNOWN"}

        # استخدام مرونة أكبر في إطار M5 السريع
        l_r = 1 if name == "M5" else 2
        swings = self._find_swings(candles, left=l_r, right=l_r)
        
        highs = swings["highs"]
        lows = swings["lows"]

        if len(highs) < 2 or len(lows) < 2:
            return {"trend": "RANGE", "bos": "NONE", "choch": "NONE", "structure": "CONSOLIDATION"}

        last_high = highs[-1]
        prev_high = highs[-2]
        last_low = lows[-1]
        prev_low = lows[-2]

        hh = last_high['price'] > prev_high['price']
        lh = last_high['price'] < prev_high['price']
        hl = last_low['price'] > prev_low['price']
        ll = last_low['price'] < prev_low['price']

        structure = "RANGE"
        if hh and hl: structure = "BULLISH"
        elif lh and ll: structure = "BEARISH"
        
        bos = "NONE"
        choch = "NONE"
        trend_status = "NEUTRAL"
        
        # الاعتماد على السعر الحالي المباشر (آخر شمعة) لفحص الكسر بدلاً من متوسط الإغلاقات
        current_price = candles[-1]['close']

        if current_price > last_high['price']:
            if structure == "BULLISH":
                bos = "BULLISH_BOS"
                trend_status = "TREND_UP"
            elif structure == "BEARISH" or structure == "RANGE":
                choch = "BULLISH_CHOCH"
                trend_status = "TRANSITION_UP"
                
        elif current_price < last_low['price']:
            if structure == "BEARISH":
                bos = "BEARISH_BOS"
                trend_status = "TREND_DOWN"
            elif structure == "BULLISH" or structure == "RANGE":
                choch = "BEARISH_CHOCH"
                trend_status = "TRANSITION_DOWN"

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
        بوابة العبور المرنة والمحسنة.
        تسمح بفرص الانعكاس السريع والتصحيحات إذا كانت مدعومة من M5.
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
        # 1. شروط الموافقة (Approval Criteria)
        # ========================================================
        if is_buy:
            # صيد ارتداد (Reversion) قوي على إطار M5 السريع
            if m5["bos"] == "BULLISH_BOS" or m5["choch"] == "BULLISH_CHOCH":
                return {"approved": True, "reason": "BUY approved: Momentum shifting up on M5 (BOS/CHoCH)."}
            
            # توافق عام صاعد (H1 صاعد، و M15 لا يعارضه)
            if h1["trend"] in ["TREND_UP", "TRANSITION_UP"] and m15["trend"] != "TREND_DOWN":
                return {"approved": True, "reason": "BUY approved: Trend Continuation (H1 Bullish context)."}

        if is_sell:
            # صيد ارتداد (Reversion) قوي على إطار M5 السريع
            if m5["bos"] == "BEARISH_BOS" or m5["choch"] == "BEARISH_CHOCH":
                return {"approved": True, "reason": "SELL approved: Momentum shifting down on M5 (BOS/CHoCH)."}
            
            # توافق عام هابط (H1 هابط، و M15 لا يعارضه)
            if h1["trend"] in ["TREND_DOWN", "TRANSITION_DOWN"] and m15["trend"] != "TREND_UP":
                return {"approved": True, "reason": "SELL approved: Trend Continuation (H1 Bearish context)."}

        # ========================================================
        # 2. شروط الرفض (إذا لم تتحقق الموافقة أعلاه)
        # ========================================================
        if is_buy and h1["trend"] == "TREND_DOWN" and m15["trend"] == "TREND_DOWN":
            return {"approved": False, "reason": "BUY rejected: Strong H1/M15 Bearish flow. No Bullish signs on M5."}
            
        if is_sell and h1["trend"] == "TREND_UP" and m15["trend"] == "TREND_UP":
            return {"approved": False, "reason": "SELL rejected: Strong H1/M15 Bullish flow. No Bearish signs on M5."}

        return {"approved": False, "reason": "NO_TRADE: Lack of compelling multi-timeframe structural evidence."}

    def evaluate_open_position(self, position_side: str, structure: Dict, quant_report: Dict) -> Dict:
        """إدارة الصفقات النشطة (Bailout)."""
        trend_h1 = structure["H1"]["trend"]
        struct_m15 = structure["M15"]["trend"]
        choch_m15 = structure["M15"]["choch"]
        
        position_side = str(position_side).upper()

        if position_side == "BUY":
            if trend_h1 in ["TREND_DOWN", "TRANSITION_DOWN"] and (struct_m15 == "TREND_DOWN" or choch_m15 == "BEARISH_CHOCH"):
                return {"action": "CLOSE", "reason": "MSCE Bailout: Total Bearish Reversal against BUY."}
        
        elif position_side == "SELL":
            if trend_h1 in ["TREND_UP", "TRANSITION_UP"] and (struct_m15 == "TREND_UP" or choch_m15 == "BULLISH_CHOCH"):
                return {"action": "CLOSE", "reason": "MSCE Bailout: Total Bullish Reversal against SELL."}

        return {"action": "HOLD", "reason": "Structure supports current position."}
