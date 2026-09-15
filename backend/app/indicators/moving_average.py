import pandas as pd

def calculate_sma(data, column: str = 'close', period: int = 14):
    """
    حساب المتوسط المتحرك البسيط (SMA) - يدعم DataFrame, Series, أو List
    """
    if isinstance(data, list):
        s = pd.Series(data)
        return s.rolling(window=period).mean()
    elif isinstance(data, pd.DataFrame):
        return data[column].rolling(window=period).mean()
    elif isinstance(data, pd.Series):
        return data.rolling(window=period).mean()
    return None

def calculate_ema(data, column: str = 'close', period: int = 200):
    """
    حساب المتوسط المتحرك الأسي (EMA) - يدعم DataFrame, Series, أو List
    """
    if isinstance(data, list):
        s = pd.Series(data)
        return s.ewm(span=period, adjust=False).mean()
    elif isinstance(data, pd.DataFrame):
        return data[column].ewm(span=period, adjust=False).mean()
    elif isinstance(data, pd.Series):
        return data.ewm(span=period, adjust=False).mean()
    return None
