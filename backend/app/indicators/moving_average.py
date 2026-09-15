import pandas as pd

def calculate_sma(df: pd.DataFrame, column: str = 'close', period: int = 14) -> pd.Series:
    """
    حساب المتوسط المتحرك البسيط (SMA) باستخدام Pandas
    """
    return df[column].rolling(window=period).mean()

def calculate_ema(df: pd.DataFrame, column: str = 'close', period: int = 200) -> pd.Series:
    """
    حساب المتوسط المتحرك الأسي (EMA) باستخدام Pandas
    متطابق مع خوارزميات التداول والمنصات الاحترافية
    """
    return df[column].ewm(span=period, adjust=False).mean()
