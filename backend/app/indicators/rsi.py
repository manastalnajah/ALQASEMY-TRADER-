import pandas as pd

def calculate_rsi(data, column='close', period=14):
    """
    حساب مؤشر القوة النسبية (RSI) بدعم كامل وآمن لـ DataFrames و Series و Lists
    """
    # 1. 🛡️ الجدار الدفاعي: تصحيح المتغيرات إذا تم تمرير (14) بدلاً من اسم العمود
    if isinstance(column, int):
        period = column
        column = 'close'
        
    # 2. 🛡️ توحيد نوع البيانات إلى Pandas Series بأمان تام
    if isinstance(data, list):
        s = pd.Series(data)
    elif isinstance(data, pd.DataFrame):
        s = data[column]
    elif isinstance(data, pd.Series):
        s = data
    else:
        return 50.0  # قيمة محايدة لحماية البوت من التوقف في حال وجود بيانات غير صالحة

    # 3. حساب الـ RSI
    delta = s.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    
    # تنعيم القيم باستخدام المتوسط الأسي
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    
    rs = ema_up / ema_down
    rsi = 100 - (100 / (1 + rs))
    
    return rsi
