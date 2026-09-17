import pandas as pd
from app.strategies.base_strategy import BaseStrategy
from app.indicators.moving_average import calculate_ema
from app.indicators.rsi import calculate_rsi
from app.indicators.adx import calculate_adx
from app.logging.logger import system_logger
from app.config import config

class GoldenSetupStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(name="golden")
        # سحب الإعدادات النهائية من ملف الكونفج
        self.ema_period = config.golden_ema_period
        self.rsi_period = config.golden_rsi_period
        self.adx_threshold = config.golden_adx_threshold
        self.max_ema_distance = config.golden_max_ema_distance

    def analyze(self, market_data: dict) -> dict:
        candles = market_data.get("candles", [])
        
        # حماية ضد نقص البيانات
        if len(candles) < self.ema_period + 10:
            return {"decision": "HOLD", "message": f"Not enough candles (Need {self.ema_period + 10})"}

        df = pd.DataFrame(candles)
        for col in ['close', 'high', 'low']:
            df[col] = df[col].astype(float)

        # حساب المؤشرات
        df['ema'] = calculate_ema(df, 'close', self.ema_period)
        df['rsi'] = calculate_rsi(df, 'close', self.rsi_period)
        adx_data = calculate_adx(df, self.rsi_period)
        df['adx'] = adx_data['ADX']
        
        last_candle = df.iloc[-2]
        prev_candle = df.iloc[-3]
        
        price = last_candle['close']
        ema_val = last_candle['ema']
        
        # فلتر التمدد السعري (Over-extension Filter)
        distance_from_ema = abs(price - ema_val) / ema_val
        if distance_from_ema > self.max_ema_distance:
            return {"decision": "HOLD", "message": f"Price over-extended ({distance_from_ema:.2%} from EMA)"}

        # شروط الشراء
        buy_trend = price > ema_val
        buy_strength = last_candle['adx'] > self.adx_threshold
        buy_momentum = prev_candle['rsi'] < 50 and last_candle['rsi'] > 50
        
        if buy_trend and buy_strength and buy_momentum:
            system_logger.info(f"🟢 GOLDEN SETUP: BUY Signal on {market_data.get('symbol')}")
            return {"decision": "BUY"}
            
        # شروط البيع
        sell_trend = price < ema_val
        sell_strength = last_candle['adx'] > self.adx_threshold
        sell_momentum = prev_candle['rsi'] > 50 and last_candle['rsi'] < 50
        
        if sell_trend and sell_strength and sell_momentum:
            system_logger.info(f"🔴 GOLDEN SETUP: SELL Signal on {market_data.get('symbol')}")
            return {"decision": "SELL"}

        return {"decision": "HOLD"}
