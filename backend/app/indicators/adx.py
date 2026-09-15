import pandas as pd
import numpy as np
from app.indicators.atr import calculate_atr, calculate_wilders_rma
def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    حساب مؤشر متوسط الاتجاه (ADX) لفلترة الأسواق العرضية
    """
    high = df['high']
    low = df['low']
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    
    up_move = high - prev_high
    down_move = prev_low - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)
    
    atr = calculate_atr(df, period)
    
    plus_di = 100 * (calculate_wilders_rma(plus_dm, period) / atr)
    minus_di = 100 * (calculate_wilders_rma(minus_dm, period) / atr)
    
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx = calculate_wilders_rma(dx, period)
    
    return pd.DataFrame({
        'ADX': adx,
        '+DI': plus_di,
        '-DI': minus_di
    })
