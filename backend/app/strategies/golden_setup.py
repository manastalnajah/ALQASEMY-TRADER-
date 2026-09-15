import pandas as pd
from app.strategies.base_strategy import BaseStrategy
from app.indicators.moving_average import calculate_ema
from app.indicators.rsi import calculate_rsi
from app.indicators.adx import calculate_adx
from app.logging.logger import system_logger

class GoldenSetupStrategy(BaseStrategy):
    def analyze(self, market_data: dict) -> dict:
        # 1. استخراج بيانات الشموع
        candles = market_data.get("candles", [])
        if len(candles) < 200:
            return {"decision": "HOLD", "message": "Not enough candles"}

        # 2. تحويل الشموع إلى Pandas DataFrame
        df = pd.DataFrame(candles)
        for col in ['close', 'high', 'low']:
            df[col] = df[col].astype(float)

        # 3. حساب المؤشرات (النواة التحليلية)
        df['ema_200'] = calculate_ema(df, 'close', 200)
        df['rsi_14'] = calculate_rsi(df, 'close', 14)
        
        adx_data = calculate_adx(df, 14)
        df['adx'] = adx_data['ADX']
        
        # 4. جلب آخر شمعة مكتملة (والتي تسبقها)
        last_candle = df.iloc[-2]
        prev_candle = df.iloc[-3]
        
        # ==========================================
        # شروط الشراء (BUY)
        # ==========================================
        buy_trend = last_candle['close'] > last_candle['ema_200']
        buy_strength = last_candle['adx'] > 25.0
        buy_momentum = prev_candle['rsi_14'] < 50 and last_candle['rsi_14'] > 50
        
        if buy_trend and buy_strength and buy_momentum:
            system_logger.info("🟢 GOLDEN SETUP: BUY Signal Detected!")
            return {"decision": "BUY"}
            
        # ==========================================
        # شروط البيع (SELL)
        # ==========================================
        sell_trend = last_candle['close'] < last_candle['ema_200']
        sell_strength = last_candle['adx'] > 25.0
        sell_momentum = prev_candle['rsi_14'] > 50 and last_candle['rsi_14'] < 50
        
        if sell_trend and sell_strength and sell_momentum:
            system_logger.info("🔴 GOLDEN SETUP: SELL Signal Detected!")
            return {"decision": "SELL"}

        return {"decision": "HOLD"}
