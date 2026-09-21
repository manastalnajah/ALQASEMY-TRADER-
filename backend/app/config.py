import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv(override=True)


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class TradingConfig:
    symbols: tuple[str, ...] = tuple(s.strip().upper() for s in os.getenv("TRADING_SYMBOLS", "EURUSD,XAUUSD").split(",") if s.strip())

    # Multi-timeframe roles.
    direction_timeframe: str = os.getenv("DIRECTION_TIMEFRAME", "H1").upper()
    confirmation_timeframe: str = os.getenv("CONFIRMATION_TIMEFRAME", "M15").upper()
    entry_timeframe: str = os.getenv("ENTRY_TIMEFRAME", "M5").upper()
    # Legacy alias kept for compatibility; execution is always on ENTRY_TIMEFRAME.
    timeframe: str = os.getenv("ENTRY_TIMEFRAME", "M5").upper()

    worker_interval_seconds: int = _int("WORKER_INTERVAL_SECONDS", 5)

    # Historical candle windows used by the MTF engine.
    direction_candle_limit: int = _int("DIRECTION_CANDLE_LIMIT", 200)
    confirmation_candle_limit: int = _int("CONFIRMATION_CANDLE_LIMIT", 300)
    entry_candle_limit: int = _int("ENTRY_CANDLE_LIMIT", 500)
    min_candles_required: int = _int("MIN_CANDLES_REQUIRED", 60)

    # Legacy setting retained for compatibility with older deployments.
    candle_limit: int = _int("CANDLE_LIMIT", 500)

    direction_candle_retention: int = _int("DIRECTION_CANDLE_RETENTION", 5000)
    confirmation_candle_retention: int = _int("CONFIRMATION_CANDLE_RETENTION", 10000)
    entry_candle_retention: int = _int("ENTRY_CANDLE_RETENTION", 20000)
    candle_sync_batch_size: int = _int("CANDLE_SYNC_BATCH_SIZE", 1000)

    enabled_strategies: tuple[str, ...] = tuple(s.strip().lower() for s in os.getenv("ENABLED_STRATEGIES", "golden").split(",") if s.strip())
    
    # ==========================================
    # 🚨 إعدادات إدارة رأس المال والاختبار
    # ==========================================
    risk_per_trade_pct: float = _float("RISK_PER_TRADE_PCT", 0.5)
    max_open_positions: int = _int("MAX_OPEN_POSITIONS", 50)
    max_pending_orders: int = _int("MAX_PENDING_ORDERS", 50)
    max_symbol_exposure_lots: float = _float("MAX_SYMBOL_EXPOSURE_LOTS", 2.0)
    
    max_daily_loss_pct: float = _float("MAX_DAILY_LOSS_PCT", 100.0) 
    max_drawdown_pct: float = _float("MAX_DRAWDOWN_PCT", 100.0)
    
    min_margin_level_pct: float = _float("MIN_MARGIN_LEVEL_PCT", 300.0)
    max_margin_usage_pct: float = _float("MAX_MARGIN_USAGE_PCT", 50.0)
    account_stale_seconds: int = _int("ACCOUNT_STALE_SECONDS", 120)
    
    signal_cooldown_minutes: int = _int("SIGNAL_COOLDOWN_MINUTES", 1) 
    pending_expiry_minutes: int = _int("PENDING_EXPIRY_MINUTES", 60)

    # ==========================================
    # 🎯 إعدادات الاستراتيجية والوقف والأهداف
    # ==========================================
    atr_period: int = _int("ATR_PERIOD", 14)
    atr_sl_multiplier: float = _float("ATR_SL_MULTIPLIER", 2.5)  # تعديل طفيف لمنع الوقف من الابتعاد المفرط
    reward_risk: float = _float("REWARD_RISK", 1.5)
    
    # تم رفع السبريد المسموح إلى 350 لضمان عدم رفض صفقات الذهب
    max_spread_points: float = _float("MAX_SPREAD_POINTS", 350.0)

    # ==========================================
    # 🧠 إعدادات الاستراتيجيات (هنا كان سبب الانهيار)
    # ==========================================
    # Golden Setup
    golden_ema_period: int = _int("GOLDEN_EMA_PERIOD", 200)
    golden_rsi_period: int = _int("GOLDEN_RSI_PERIOD", 14)
    golden_adx_threshold: float = _float("GOLDEN_ADX_THRESHOLD", 25.0)
    golden_max_ema_distance: float = _float("GOLDEN_MAX_EMA_DISTANCE", 0.015) 
    
    # RSI Reversion
    rsi_oversold_level: float = _float("RSI_OVERSOLD_LEVEL", 30.0)
    rsi_overbought_level: float = _float("RSI_OVERBOUGHT_LEVEL", 70.0)

    # ==========================================
    # 🔐 مفاتيح الاتصال
    # ==========================================
    allow_smart_limits: bool = os.getenv("ALLOW_SMART_LIMITS", "false").lower() == "true"
    allow_scalping: bool = os.getenv("ALLOW_SCALPING", "false").lower() == "true"
    mt5_api_key: str = os.getenv("MT5_API_KEY", "")
    require_mt5_api_key: bool = os.getenv("REQUIRE_MT5_API_KEY", "true").lower() == "true"
    control_api_key: str = os.getenv("CONTROL_API_KEY", "AlqasemyTrader2026_SecureKey!@")
    require_control_api_key: bool = os.getenv("REQUIRE_CONTROL_API_KEY", "true").lower() == "true"

config = TradingConfig()
