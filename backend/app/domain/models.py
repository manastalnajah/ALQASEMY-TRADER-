from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Float,
    DateTime,
    Integer,
    Boolean,
    Numeric,
    Text,
    BigInteger,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from database import Base


# ============================================================
# TRADE COMMANDS
# ============================================================

class TradeCommand(Base):
    __tablename__ = "trade_commands"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        server_default=text("uuid_generate_v4()"),
    )

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trading_accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    ea_id = Column(String, nullable=False, default="", index=True)

    symbol = Column(String, nullable=False, index=True)

    order_type = Column(String, nullable=False)

    lot_size = Column(Float, nullable=False)

    entry_price = Column(Float, nullable=False, default=0.0)

    stop_loss = Column(Float, nullable=False, default=0.0)

    take_profit = Column(Float, nullable=False, default=0.0)

    status = Column(
        String,
        nullable=False,
        default="pending",
        index=True,
    )

    signal_key = Column(
        String,
        nullable=False,
        default="",
    )

    strategy_name = Column(
        String,
        nullable=False,
        default="",
    )

    error_message = Column(
        String,
        nullable=True,
        default="",
    )

    mt5_ticket = Column(
        BigInteger,
        nullable=True,
        index=True,
    )

    mt5_order_ticket = Column(
        BigInteger,
        nullable=True,
        index=True,
    )

    mt5_deal_ticket = Column(
        BigInteger,
        nullable=True,
        index=True,
    )

    fill_price = Column(
        Float,
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        index=True,
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    __table_args__ = (
        Index(
            "ix_trade_commands_symbol_status_created",
            "symbol",
            "status",
            "created_at",
        ),

        Index(
            "idx_trade_commands_account_status_created",
            "account_id",
            "status",
            "created_at",
        ),

        Index(
            "ix_trade_commands_symbol_status_created",
            "symbol",
            "status",
            "created_at",
        ),

        # يجب أن يتطابق مع الـ partial unique index الموجود في DB.
        # لا نعيد إنشاءه من SQLAlchemy لأن WHERE يحتاج PostgreSQL dialect.
        #
        # ux_trade_commands_account_signal_key
        # موجود أصلًا في قاعدة البيانات.
    )


# ============================================================
# CANDLES
# ============================================================

class Candle(Base):
    __tablename__ = "candles"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        server_default=text("uuid_generate_v4()"),
    )

    symbol_name = Column(
        String,
        nullable=False,
        index=True,
    )

    timeframe = Column(
        String,
        nullable=False,
        default="M5",
        index=True,
    )

    open_time = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )

    open = Column(
        Numeric,
        nullable=False,
    )

    high = Column(
        Numeric,
        nullable=False,
    )

    low = Column(
        Numeric,
        nullable=False,
    )

    close = Column(
        Numeric,
        nullable=False,
    )

    volume = Column(
        BigInteger,
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=True,
        server_default=text("NOW()"),
    )

    __table_args__ = (
        Index(
            "idx_candles_lookup",
            "symbol_name",
            "timeframe",
            "open_time",
        ),

        # القيد UNIQUE الموجود فعليًا في DB
        UniqueConstraint(
            "symbol_name",
            "timeframe",
            "open_time",
            name="candles_symbol_name_timeframe_open_time_key",
        ),
    )


# ============================================================
# SYMBOL SPECS
# ============================================================

class SymbolSpec(Base):
    __tablename__ = "symbol_specs"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    symbol = Column(
        String,
        unique=True,
        nullable=False,
        index=True,
    )

    digits = Column(
        Integer,
        nullable=False,
        default=5,
    )

    point = Column(
        Float,
        nullable=False,
        default=0.00001,
    )

    tick_size = Column(
        Float,
        nullable=False,
        default=0.00001,
    )

    tick_value = Column(
        Float,
        nullable=False,
        default=0.0,
    )

    volume_min = Column(
        Float,
        nullable=False,
        default=0.01,
    )

    volume_max = Column(
        Float,
        nullable=False,
        default=100.0,
    )

    volume_step = Column(
        Float,
        nullable=False,
        default=0.01,
    )

    stops_level_points = Column(
        Integer,
        nullable=False,
        default=0,
    )

    contract_size = Column(
        Float,
        nullable=False,
        default=0.0,
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )


# ============================================================
# RISK STATE
# ============================================================

class RiskState(Base):
    __tablename__ = "risk_state"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trading_accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    day_key = Column(
        String,
        nullable=False,
        index=True,
    )

    day_start_equity = Column(
        Float,
        nullable=False,
        default=0.0,
    )

    high_water_equity = Column(
        Float,
        nullable=False,
        default=0.0,
    )

    trading_halted = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    halt_reason = Column(
        String,
        nullable=False,
        default="",
    )

    daily_pnl = Column(
        Float,
        nullable=False,
        default=0.0,
    )

    daily_loss = Column(
        Float,
        nullable=False,
        default=0.0,
    )

    daily_trades = Column(
        Integer,
        nullable=False,
        default=0,
    )

    daily_winning_trades = Column(
        Integer,
        nullable=False,
        default=0,
    )

    daily_losing_trades = Column(
        Integer,
        nullable=False,
        default=0,
    )

    consecutive_losses = Column(
        Integer,
        nullable=False,
        default=0,
    )

    current_drawdown_percent = Column(
        Float,
        nullable=False,
        default=0.0,
    )

    last_trade_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_loss_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    __table_args__ = (
        Index(
            "idx_risk_state_account_day",
            "account_id",
            "day_key",
        ),

        # الـ unique partial index الحقيقي موجود في DB:
        # ux_risk_state_account_day
    )


# ============================================================
# POSITION SNAPSHOT
# ============================================================

class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"

    account_number = Column(
        BigInteger,
        primary_key=True,
    )

    last_sync = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )


# ============================================================
# LIVE POSITIONS
# ============================================================

class LivePosition(Base):
    __tablename__ = "live_positions"

    ticket = Column(
        String,
        primary_key=True,
    )

    account_number = Column(
        BigInteger,
        nullable=False,
        index=True,
    )

    symbol = Column(
        String,
        nullable=False,
        index=True,
    )

    side = Column(
        String,
        nullable=False,
    )

    volume = Column(
        Float,
        nullable=False,
    )

    price_open = Column(
        Float,
        nullable=False,
    )

    stop_loss = Column(
        Float,
        nullable=False,
        default=0.0,
    )

    take_profit = Column(
        Float,
        nullable=False,
        default=0.0,
    )

    profit = Column(
        Float,
        nullable=False,
        default=0.0,
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )


# ============================================================
# PENDING ORDERS
# ============================================================

class PendingOrder(Base):
    __tablename__ = "pending_orders"

    ticket = Column(
        String,
        primary_key=True,
    )

    account_number = Column(
        BigInteger,
        nullable=False,
        index=True,
    )

    symbol = Column(
        String,
        nullable=False,
        index=True,
    )

    side = Column(
        String,
        nullable=False,
    )

    volume = Column(
        Float,
        nullable=False,
    )

    price_open = Column(
        Float,
        nullable=False,
    )

    stop_loss = Column(
        Float,
        nullable=False,
        default=0.0,
    )

    take_profit = Column(
        Float,
        nullable=False,
        default=0.0,
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )


# ============================================================
# BOT STATE
# ============================================================

class BotState(Base):
    __tablename__ = "bot_state"

    id = Column(
        Integer,
        primary_key=True,
        default=1,
    )

    is_running = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    status = Column(
        String,
        nullable=False,
        default="STOPPED",
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
