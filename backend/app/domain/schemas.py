# ============================================================
# app/domain/schemas.py
# النسخة المعدلة — V2
# تدعم Smart Position Management + إصلاحات المزامنة
# ============================================================

from datetime import datetime
from enum import Enum
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

    # ✅ حقل account_number لمطابقة قاعدة البيانات (Supabase) والتطبيق
    account_number: Optional[int] = Field(default=None)

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

    # ✅ حقل account_number في الاستجابة
    account_number: Optional[int] = None

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
    للأوامر المعلقة (فتح صفقات جديدة).
    """

    id: UUID

    command_id: str

    account_id: Optional[UUID] = None

    # ✅ إضافة account_number للتحقق من الملكية داخل EA
    account_number: Optional[int] = None

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

    # ✅ إضافة account_number للتحقق من الملكية
    account_number: Optional[int] = None


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

    # ✅ إضافة executed_volume المذكور في EA
    executed_volume: Optional[float] = None

    # ✅ رمز نتيجة MT5 لتشخيص الرفض
    mt5_retcode: Optional[int] = None


# ============================================================
# SYMBOL SPECIFICATION
# ============================================================

class SymbolSpecSync(BaseModel):
    """
    مواصفات الرمز القادمة من MT5 (محدثة لتطابق الإكسبيرت).

    ملاحظة: نحتفظ بأسماء min_lot / max_lot / lot_step لأن EA يرسلها بهذه الأسماء.
    طبقة API هي المسؤولة عن تحويلها إلى volume_min / volume_max / volume_step
    عند الكتابة في قاعدة البيانات.
    """
    symbol: str = Field(min_length=1, max_length=64)
    digits: int = Field(ge=0, le=20)
    point: float = Field(gt=0)
    tick_size: float = Field(gt=0)
    tick_value: float = Field(ge=0)

    # حقول متوافقة مع الإكسبيرت
    min_lot: float = Field(default=0.01, gt=0)
    max_lot: float = Field(default=100.0, gt=0)
    lot_step: float = Field(default=0.01, gt=0)
    spread: int = Field(default=0, ge=0)

    contract_size: float = Field(default=100000.0, ge=0)

    # ✅ إضافة stops_level_points — مطلوب لتحقق EA من المسافات الدنيا
    stops_level_points: int = Field(default=0, ge=0)

    # ✅ إضافة freeze_level_points — مطلوب قبل تعديل SL/TP
    # بعض الوسطاء يمنعون التعديل عندما يكون السعر داخل نطاق التجميد
    freeze_level_points: int = Field(default=0, ge=0)


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

    التعديلات الجديدة:
    - current_price: السعر الحالي الحقيقي للصفقة (كان مفقودًا، وكان API يستخدم price_open خطأً)
    - open_time: وقت فتح الصفقة (بدلًا من updated_at الذي لا يمثل وقت الفتح)
    - identifier: POSITION_IDENTIFIER لمعالجة تغير تذكرة Netting
    - magic: للتحقق من ملكية الصفقة
    """

    ticket: int

    # ✅ هوية ثابتة للمركز حتى لو تغيرت التذكرة (حسابات Netting)
    identifier: Optional[int] = None

    # ✅ رقم Magic للتحقق من ملكية الصفقة
    magic: Optional[int] = None

    symbol: str

    side: str

    volume: float = Field(
        gt=0,
    )

    price_open: float

    # ✅ السعر الحالي الحقيقي للصفقة (إصلاح خطأ curr_p = price_open)
    current_price: float = Field(default=0.0, ge=0)

    stop_loss: float = Field(
        ge=0,
    )

    take_profit: float = Field(
        ge=0,
    )

    profit: float

    # ✅ وقت فتح الصفقة الحقيقي
    open_time: Optional[datetime] = None

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
# TRADE HISTORY SYNC (الأرشيف وسجل الصفقات المغلقة)
# ============================================================

class HistoryDealItem(BaseModel):
    """
    صفقة مغلقة أو منفذة تاريخياً قادمة من دفاتر MT5.
    """
    deal_ticket: int
    order_ticket: int
    position_ticket: int
    symbol: str
    side: str
    volume: float = Field(gt=0)
    open_price: float
    close_price: float
    sl: Optional[float] = 0.0
    tp: Optional[float] = 0.0
    profit: float
    commission: Optional[float] = 0.0
    swap: Optional[float] = 0.0
    comment: Optional[str] = ""
    open_time: datetime
    close_time: datetime


class HistorySyncRequest(BaseModel):
    """
    طلب مزامنة دفعة من الصفقات المغلقة لأرشيف الحساب.
    """
    account_number: int = Field(gt=0)
    ea_id: str = ""
    magic: Optional[int] = None
    deals: list[HistoryDealItem] = Field(default_factory=list)


# ============================================================
# CANDLE SYNC
# ============================================================

class CandleItem(BaseModel):
    """
    شمعة قادمة من MT5.

    التعديل الجديد:
    - is_closed: يميّز الشمعة المغلقة عن الشمعة الحالية.
      يُستخدم لتجنب تغيّر قيم RSI و Z-Score أثناء تكوّن الشمعة.
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

    # ✅ تمييز الشمعة المغلقة
    is_closed: bool = Field(default=True)


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
# POSITION MANAGEMENT (جديد)
# إدارة الصفقات المفتوحة: تعديل SL/TP، الإغلاق، الإغلاق الجزئي
# ============================================================

class PositionManagementAction(str, Enum):
    """
    أنواع الأوامر التي يمكن إرسالها لإدارة صفقة مفتوحة.

    ملاحظة معمارية:
    - MOVE_TO_BREAKEVEN و TRAILING_STOP قرارات داخلية في محرك الإدارة.
    - يُرسل للـ EA أمر موحّد MODIFY_SL_TP لتقليل أنواع الأوامر المطلوبة.
    """
    MODIFY_SL_TP = "MODIFY_SL_TP"
    CLOSE_POSITION = "CLOSE_POSITION"
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    MOVE_TO_BREAKEVEN = "MOVE_TO_BREAKEVEN"
    TRAILING_STOP = "TRAILING_STOP"


class PositionManagementCommandCreate(BaseModel):
    """
    نموذج داخلي لإنشاء أمر إدارة صفقة في قاعدة البيانات.
    لا يُستقبل مباشرة من خارج النظام.
    """
    account_id: Optional[UUID] = None
    account_number: int = Field(gt=0)
    ea_id: str = Field(default="", max_length=128)

    position_ticket: int = Field(gt=0)
    position_identifier: Optional[int] = None

    symbol: str = Field(min_length=1, max_length=64)
    action: PositionManagementAction

    # قيم اختيارية حسب نوع الأمر
    new_sl: Optional[float] = None
    new_tp: Optional[float] = None
    close_volume: Optional[float] = None

    # سياق القرار (للتشخيص والتحليل)
    reason: str = Field(default="", max_length=255)
    risk_score: Optional[float] = None

    # وقت انتهاء صلاحية الأمر
    expires_at: Optional[datetime] = None


class PositionManagementCommandResponse(BaseModel):
    """
    الاستجابة التي يقرأها EA عند polling أوامر الإدارة.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    command_id: str

    account_number: int
    ea_id: str = ""

    position_ticket: int
    position_identifier: Optional[int] = None

    symbol: str
    action: str

    new_sl: Optional[float] = None
    new_tp: Optional[float] = None
    close_volume: Optional[float] = None

    reason: str = ""

    status: str = "pending"

    created_at: datetime
    created_epoch: Optional[float] = None
    expires_at: Optional[datetime] = None
    expires_epoch: Optional[float] = None


class PositionManagementAck(BaseModel):
    """
    تأكيد استلام EA لأمر إدارة صفقة.
    """
    ea_id: str = Field(default="", max_length=128)
    account_number: Optional[int] = None


class PositionManagementReport(BaseModel):
    """
    تقرير EA عن نتيجة تنفيذ أمر إدارة الصفقة.

    ملاحظة:
    mt5_retcode ضروري للتمييز بين:
    - نجاح التعديل
    - Invalid Stops
    - Freeze Level
    - Position Not Found
    - Market Closed
    """
    status: str = Field(min_length=1, max_length=32)

    ea_id: str = Field(default="", max_length=128)
    account_number: Optional[int] = None

    position_ticket: int

    executed_sl: Optional[float] = None
    executed_tp: Optional[float] = None
    executed_volume: Optional[float] = None

    # ✅ رمز نتيجة MT5
    mt5_retcode: Optional[int] = None

    error_message: Optional[str] = None


class PositionManagementStateResponse(BaseModel):
    """
    حالة إدارة صفقة مفتوحة (لعرضها في لوحة التحكم).
    """
    model_config = ConfigDict(from_attributes=True)

    account_number: int
    position_ticket: int
    symbol: str

    max_floating_profit: float = 0.0
    max_favorable_price: Optional[float] = None

    initial_risk: Optional[float] = None
    initial_sl: Optional[float] = None

    break_even_activated: bool = False
    profit_lock_activated: bool = False
    trailing_activated: bool = False

    last_management_action: Optional[str] = None
    last_action_at: Optional[datetime] = None

    updated_at: Optional[datetime] = None


# ============================================================
# POSITION RISK ANALYSIS (جديد)
# تقرير تحليل مخاطر الصفقة المفتوحة
# ============================================================

class PositionRiskAnalysis(BaseModel):
    """
    تقرير تحليل مخاطر صفقة مفتوحة.

    يُستخدم من PositionRiskAnalyzer قبل إنشاء أمر إدارة.
    """
    position_ticket: int
    symbol: str

    # تقييم الحالة
    tp_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    current_r: float = 0.0
    peak_r: float = 0.0

    # سياق السوق
    market_regime: Optional[str] = None
    hurst_exponent: Optional[float] = None
    z_score: Optional[float] = None

    # الزخم
    rsi: Optional[float] = None
    momentum_weakening: bool = False

    # التوصية
    reversal_score: int = Field(default=0, ge=0, le=100)
    recommended_action: Optional[str] = None
    reason: str = ""


# ============================================================
# GENERIC API RESPONSE
# ============================================================

class MessageResponse(BaseModel):
    success: bool

    message: Optional[str] = None
