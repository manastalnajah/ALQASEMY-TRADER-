import pandas as pd

def calculate_wilders_rma(data: pd.Series, period: int) -> pd.Series:
    """
    معادلة تنعيم وايلدر (Wilder's Smoothing) المطابقة لمؤشرات MT5
    """
    return data.ewm(alpha=1/period, adjust=False).mean()

def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    حساب مؤشر متوسط المدى الحقيقي (ATR) باستخدام Pandas
    يتوافق تماماً مع المدخلات التي ترسلها ملفات adx.py و rsi.py
    """
    high = df['high']
    low = df['low']
    prev_close = df['close'].shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    return calculate_wilders_rma(tr, period)
