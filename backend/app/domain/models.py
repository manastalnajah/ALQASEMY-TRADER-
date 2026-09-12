from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime, Integer, Boolean, UniqueConstraint, Index, text
from sqlalchemy.dialects.postgresql import UUID
from database import Base


class TradeCommand(Base):
    __tablename__ = "trade_commands"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True,
                server_default=text("uuid_generate_v4()"))
    symbol = Column(String, index=True, nullable=False)
    order_type = Column(String, nullable=False)
    lot_size = Column(Float, nullable=False)
    entry_price = Column(Float, default=0.0, nullable=False)
    stop_loss = Column(Float, default=0.0, nullable=False)
    take_profit = Column(Float, default=0.0, nullable=False)
    status = Column(String, default="pending", index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    strategy_name = Column(String, default="", nullable=False)
    signal_key = Column(String, default="", index=True, nullable=False)
    ea_id = Column(String, default="", index=True, nullable=False)
    error_message = Column(String, default="")

    __table_args__ = (
        Index("ix_trade_commands_symbol_status_created", "symbol", "status", "created_at"),
    )


class Candle(Base):
    __tablename__ = "candles"

    id = Column(UUID(as_uuid=True), primary_key=True, index=True,
                server_default=text("uuid_generate_v4()"))
    symbol_name = Column(String, index=True, nullable=False)
    timeframe = Column(String, index=True, nullable=False, default="M5")
    open_time = Column(String, index=True, nullable=False)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint('symbol_name', 'timeframe', 'open_time', name='uix_symbol_timeframe_time'),
    )


class SymbolSpec(Base):
    __tablename__ = "symbol_specs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, unique=True, nullable=False, index=True)
    digits = Column(Integer, nullable=False, default=5)
    point = Column(Float, nullable=False, default=0.00001)
    tick_size = Column(Float, nullable=False, default=0.00001)
    tick_value = Column(Float, nullable=False, default=0.0)
    volume_min = Column(Float, nullable=False, default=0.01)
    volume_max = Column(Float, nullable=False, default=100.0)
    volume_step = Column(Float, nullable=False, default=0.01)
    stops_level_points = Column(Integer, nullable=False, default=0)
    contract_size = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class RiskState(Base):
    __tablename__ = "risk_state"

    id = Column(Integer, primary_key=True, default=1)
    day_key = Column(String, nullable=False, index=True)
    day_start_equity = Column(Float, nullable=False, default=0.0)
    high_water_equity = Column(Float, nullable=False, default=0.0)
    trading_halted = Column(Boolean, nullable=False, default=False)
    halt_reason = Column(String, nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"

    account_number = Column(Integer, primary_key=True)
    last_sync = Column(DateTime, nullable=False, default=datetime.utcnow)


class LivePosition(Base):
    __tablename__ = "live_positions"

    ticket = Column(String, primary_key=True)
    account_number = Column(Integer, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    volume = Column(Float, nullable=False)
    price_open = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False, default=0.0)
    take_profit = Column(Float, nullable=False, default=0.0)
    profit = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PendingOrder(Base):
    __tablename__ = "pending_orders"

    ticket = Column(String, primary_key=True)
    account_number = Column(Integer, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    side = Column(String, nullable=False)
    volume = Column(Float, nullable=False)
    price_open = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False, default=0.0)
    take_profit = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class BotState(Base):
    __tablename__ = "bot_state"

    id = Column(Integer, primary_key=True, default=1)
    is_running = Column(Boolean, nullable=False, default=False)
    status = Column(String, nullable=False, default="stopped")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
