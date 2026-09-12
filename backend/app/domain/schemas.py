from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, ConfigDict


# ============================================================
# TRADE COMMAND
# ============================================================

class CommandCreate(BaseModel):
    """
    إنشاء أمر تداول جديد في trade_commands.

    ملاحظة:
    account_id اختياري حاليًا لأن قاعدة البيانات تسمح بقيم NULL
    للتوافق مع الأوامر القديمة.
    """

    account_id: Optional[UUID] = None

    symbol: str = Field(
        min_length=1,
        max_length=32,
    )

    order_type: str = Field(
        min_length=1,
        max_length=32,
    )

    lot_size: float = Field(
        gt=0,
    )

    entry_price: float = Field(
        gt=0,
    )

    stop_loss: float = Field(
        gt=0,
    )

    take_profit: float = Field(
        gt=0,
    )

    strategy_name: str = Field(
        default="manual",
        max_length=128,
    )

    signal_key: str = Field(
        default="",
        max_length=255,
    )

    ea_id: str = Field(
        default="",
        max_length=128,
    )


class CommandResponse(BaseModel):
    """
    الاستجابة الكاملة لأمر تداول من trade_commands.
    """

    model_config = ConfigDict(
        from_attributes=True
    )

    id: UUID

    account_id: Optional[UUID] = None

    ea_id: str = ""

    symbol: str

    order_type: str

    lot_size: float

    entry_price: float

    stop_loss: float

    take_profit: float

    status: str

    signal_key: str = ""

    strategy_name: str = ""

    error_message: Optional[str] = None

    mt5_ticket: Optional[int] = None

    mt5_order_ticket: Optional[int] = None

    mt5_deal_ticket: Optional[int] = None

    fill_price: Optional[float] = None

    created_at: datetime

    updated_at: Optional[datetime] = None


# ============================================================
# MT5 COMMAND POLLING RESPONSE
# ============================================================

class CommandPollResponse(BaseModel):
    """
    البيانات التي يحتاجها Expert Advisor عند polling
    للأوامر المعلقة.
    """

    id: UUID

    command_id: str

    account_id: Optional[UUID] = None

    ea_id: str = ""

    symbol: str

    order_type: str

    side: str

    volume: float

    entry_price: float

    sl: float

    tp: float

    status: str

    strategy_name: str = ""

    signal_key: str = ""

    created_at: datetime

    created_epoch: Optional[float] = None

    expires_at: Optional[datetime] = None

    expires_epoch: Optional[float] = None


# ============================================================
# COMMAND ACK
# ============================================================

class CommandAckRequest(BaseModel):
    """
    تأكيد استلام EA للأمر قبل محاولة التنفيذ.
    """

    ea_id: str = Field(
        default="",
        max_length=128,
    )

    account_id: Optional[UUID] = None


class CommandAckResponse(BaseModel):
    success: bool

    command_id: str

    status: str

    message: Optional[str] = None


# ============================================================
# COMMAND EXECUTION REPORT
# ============================================================

class CommandReportRequest(BaseModel):
    """
    تقرير EA عن النتيجة الفعلية للتنفيذ.
    """

    status: str = Field(
        min_length=1,
        max_length=32,
    )

    ea_id: str = Field(
        default="",
        max_length=128,
    )

    account_id: Optional[UUID] = None

    mt5_ticket: Optional[int] = None

    mt5_order_ticket: Optional[int] = None

    mt5_deal_ticket: Optional[int] = None

    fill_price: Optional[float] = None

    error_message: Optional[str] = None


# ============================================================
# SYMBOL SPECIFICATION
# ============================================================

class SymbolSpecSync(BaseModel):
    """
    مواصفات الرمز القادمة من MT5.
    """

    symbol: str = Field(
        min_length=1,
        max_length=64,
    )

    digits: int = Field(
        ge=0,
        le=20,
    )

    point: float = Field(
        gt=0,
    )

    tick_size: float = Field(
        gt=0,
    )

    tick_value: float = Field(
        ge=0,
    )

    volume_min: float = Field(
        gt=0,
    )

    volume_max: float = Field(
        gt=0,
    )

    volume_step: float = Field(
        gt=0,
    )

    stops_level_points: int = Field(
        default=0,
        ge=0,
    )

    contract_size: float = Field(
        default=0.0,
        ge=0,
    )


# ============================================================
# ACCOUNT HEARTBEAT / SYNC
# ============================================================

class AccountHeartbeat(BaseModel):
    """
    حالة حساب MT5 الحالية.
    """

    account_number: int = Field(
        gt=0,
    )

    balance: float

    equity: float

    margin: float = Field(
        ge=0,
    )

    free_margin: float

    profit: float

    is_connected: bool

    margin_level: Optional[float] = None

    server: Optional[str] = None

    currency: Optional[str] = None

    leverage: Optional[int] = Field(
        default=None,
        gt=0,
    )

    is_trade_allowed: Optional[bool] = None

    ea_id: Optional[str] = None

    ea_version: Optional[str] = None


# ============================================================
# POSITION SYNC
# ============================================================

class PositionItem(BaseModel):
    """
    مركز تداول مفتوح من MT5.
    """

    ticket: int

    symbol: str

    side: str

    volume: float = Field(
        gt=0,
    )

    price_open: float

    stop_loss: float = Field(
        ge=0,
    )

    take_profit: float = Field(
        ge=0,
    )

    profit: float

    updated_at: Optional[datetime] = None


class PositionsSyncRequest(BaseModel):
    account_number: int = Field(
        gt=0,
    )

    ea_id: str = ""

    magic: Optional[int] = None

    positions: list[PositionItem] = Field(
        default_factory=list,
    )


# ============================================================
# PENDING ORDER SYNC
# ============================================================

class PendingOrderItem(BaseModel):
    """
    أمر معلق موجود حاليًا في MT5.
    """

    ticket: int

    symbol: str

    side: str

    volume: float = Field(
        gt=0,
    )

    price_open: float

    stop_loss: float = Field(
        ge=0,
    )

    take_profit: float = Field(
        ge=0,
    )

    updated_at: Optional[datetime] = None


class PendingOrdersSyncRequest(BaseModel):
    account_number: int = Field(
        gt=0,
    )

    ea_id: str = ""

    magic: Optional[int] = None

    orders: list[PendingOrderItem] = Field(
        default_factory=list,
    )


# ============================================================
# CANDLE SYNC
# ============================================================

class CandleItem(BaseModel):
    """
    شمعة مغلقة قادمة من MT5.
    """

    symbol: str = Field(
        min_length=1,
        max_length=64,
    )

    timeframe: str = Field(
        min_length=1,
        max_length=16,
    )

    open_time: datetime

    open: float = Field(
        gt=0,
    )

    high: float = Field(
        gt=0,
    )

    low: float = Field(
        gt=0,
    )

    close: float = Field(
        gt=0,
    )

    volume: int = Field(
        ge=0,
    )


class CandlesSyncRequest(BaseModel):
    """
    دفعة شموع من MT5 إلى backend.
    """

    symbol: str

    timeframe: str

    candles: list[CandleItem] = Field(
        default_factory=list,
    )

    ea_id: Optional[str] = None


# ============================================================
# GENERIC API RESPONSE
# ============================================================

class MessageResponse(BaseModel):
    success: bool

    message: Optional[str] = None
