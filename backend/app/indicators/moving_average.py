def calculate_sma(prices: list[float], period: int) -> float | None:
    """
    دالة لحساب المتوسط المتحرك البسيط (Simple Moving Average).
    تستقبل قائمة بأسعار الإغلاق السابقة، وعدد الشموع (period).
    """
    # التأكد من وجود بيانات كافية للحساب لمنع الأخطاء
    if not prices or len(prices) < period:
        return None
        
    # أخذ آخر شموع بناءً على العدد المطلوب
    recent_prices = prices[-period:]
    
    # حساب المتوسط (مجموع الأسعار مقسوماً على عددها)
    sma = sum(recent_prices) / period
    return round(sma, 5)

def calculate_ema(prices: list[float], period: int) -> float | None:
    """
    دالة لحساب المتوسط المتحرك الأُسي (Exponential Moving Average).
    وهو يركز أكثر على الأسعار الحديثة ليعطي إشارات أسرع.
    """
    if not prices or len(prices) < period:
        return None
        
    multiplier = 2 / (period + 1)
    # نبدأ بمتوسط بسيط كقيمة أولية
    ema = sum(prices[:period]) / period
    
    # حساب القيمة الأسية لبقية الأسعار
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
        
    return round(ema, 5)