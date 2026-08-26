def calculate_rsi(prices: list[float], period: int = 14) -> float | None:
    """
    دالة لحساب مؤشر القوة النسبية (Relative Strength Index).
    الذي يقيس سرعة وتغير حركات السعر لاكتشاف مناطق التشبع.
    """
    if not prices or len(prices) < period + 1:
        return None
        
    gains = []
    losses = []
    
    # حساب التغير في السعر بين كل شمعة والتي قبلها
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        if change > 0:
            gains.append(change)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(change))
            
    # حساب متوسط المكاسب والخسائر للفترة المحددة
    recent_gains = gains[-period:]
    recent_losses = losses[-period:]
    
    avg_gain = sum(recent_gains) / period
    avg_loss = sum(recent_losses) / period
    
    # إذا لم تكن هناك خسائر، السعر في صعود مستمر (تشبع شرائي أقصى)
    if avg_loss == 0:
        return 100.0
        
    # المعادلة الرئيسية للمؤشر
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return round(rsi, 2)