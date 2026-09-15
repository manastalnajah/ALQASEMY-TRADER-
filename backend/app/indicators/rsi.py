import pandas as pd
from .atr import calculate_wilders_rma

def calculate_rsi(df: pd.DataFrame, column: str = 'close', period: int = 14) -> pd.Series:
    """
    حساب مؤشر القوة النسبية (RSI) بدقة MT5 باستخدام Pandas وتنعيم وايلدر (RMA)
    """
    delta = df[column].diff()
    
    # فصل المكاسب عن الخسائر
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    
    # تطبيق تنعيم وايلدر الأساسي للمطابقة مع الميتاتريدر
    avg_gain = calculate_wilders_rma(gain, period)
    avg_loss = calculate_wilders_rma(loss, period)
    
    # حساب قيمة RS و RSI
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    # معالجة حالات القسمة على صفر أو القيم المفقودة
    return rsi.fillna(100).where(avg_loss != 0, 100.0)
