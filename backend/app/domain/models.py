# ============================================================
# app/domain/models.py
# النسخة المعدلة — V2
# تدعم Smart Position Management + قيود منع التكرار
# ============================================================

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
# TRADING ACCOUNTS
# ============================================================

class TradingAccount(Base):
    __tablename__ = "trading_accounts"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
        server_default=text("uuid_generate_v4()"),
    )

    account_number = Column(
        BigInteger,
        unique=True,
        nullable=False,
        index=True,
    )

    ea_id = Column(
        String,
        nullable=False,
        default="",
        index=True,
    )

    balance = Column(Float, nullable=False, default=0.0)
    equity = Column(Float, nullable=False, default=0.0)
    margin = Column(Float, nullable=False, default=0.0)
    free_margin = Column(Float, nullable=False, default=0.0)
    margin_level = Column(Float, nullable=False, default=0.0)

    is_connected = Column(Boolean, nullable=False, default=False)

    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    last_sync = Column(DateTime(timezone=True), nullable=True)

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=text("NOW()"),
    )


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

    # ✅ حقل account_number
    account_number = Column(
        BigInteger,
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

    # ✅ إضافة executed_volume لتخزين الحجم المنفذ فعليًا (قد يختلف عن lot_size)
    executed_volume = Column(
        Float,
        nullable=True,
    )

    # ✅ إضافة mt5_retcode لتشخيص رفض الوسيط
    mt5_retcode = Column(
        Integer,
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
        onupdate=text("NOW()"),
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

        # ✅ قيد فريد لمنع تكرار الأوامر تحت التزامن.
        # ملاحظة: account_id قد يكون NULL، و PostgreSQL يسمح بتكرار NULL
        # ضمن القيود الفريدة. لذلك سنستخدم فهرسًا جزئيًا عبر Migration
        # يستثني NULL لضمان فعالية القيد للأوامر الفعلية.
        UniqueConstraint(
            "account_id",
            "signal_key",
            name="uq_trade_commands_account_signal",
        ),
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

    open = Column(Numeric, nullable=False)
    high = Column(Numeric, nullable=False)
    low = Column(Numeric, nullable=False)
    close = Column(Numeric, nullable=False)
    volume = Column(BigInteger, nullable=False)

    # ✅ إضافة is_closed لتمييز الشمعة المغلقة عن الحالية
    is_closed = Column(
        Boolean,
        nullable=False,
        default=True,
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

    digits = Column(Integer, nullable=False, default=5)
    point = Column(Float, nullable=False, default=0.00001)
    tick_size = Column(Float, nullable=False, default=0.00001)
    tick_value = Column(Float, nullable=False, default=0.0)

    volume_min = Column(Float, nullable=False, default=0.01)
    volume_max = Column(Float, nullable=False, default=100.0)
    volume_step = Column(Float, nullable=False, default=0.01)

    stops_level_points = Column(Integer, nullable=False, default=0)

    # ✅ إضافة freeze_level_points — مطلوب قبل تعديل SL/TP
    freeze_level_points = Column(Integer, nullable=False, default=0)

    contract_size = Column(Float, nullable=False, default=0.0)

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=text("NOW()"),
    )


# ============================================================
# RISK STATE
# ============================================================

class RiskState(Base):
    __tablename__ = "risk_state"

    id = Column(Integer, primary_key=True, autoincrement=True)

    account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("trading_accounts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    day_key = Column(String, nullable=False, index=True)

    day_start_equity = Column(Float, nullable=False, default=0.0)
    high_water_equity = Column(Float, nullable=False, default=0.0)

    trading_halted = Column(Boolean, nullable=False, default=False)
    halt_reason = Column(String, nullable=False, default="")

    daily_pnl = Column(Float, nullable=False, default=0.0)
    daily_loss = Column(Float, nullable=False, default=0.0)
    daily_trades = Column(Integer, nullable=False, default=0)
    daily_winning_trades = Column(Integer, nullable=False, default=0)
    daily_losing_trades = Column(Integer, nullable=False, default=0)
    consecutive_losses = Column(Integer, nullable=False, default=0)
    current_drawdown_percent = Column(Float, nullable=False, default=0.0)

    last_trade_at = Column(DateTime(timezone=True), nullable=True)
    last_loss_at = Column(DateTime(timezone=True), nullable=True)

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=text("NOW()"),
    )

    __table_args__ = (
        Index("idx_risk_state_account_day", "account_id", "day_key"),
    )


# ============================================================
# POSITION SNAPSHOT
# ============================================================

class PositionSnapshot(Base):
    __tablename__ = "position_snapshots"

    account_number = Column(BigInteger, primary_key=True)

    last_sync = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )


# ============================================================
# OPEN POSITIONS
# ============================================================

class OpenPosition(Base):
    __tablename__ = "open_positions"

    ticket = Column(BigInteger, primary_key=True)

    account_number = Column(
        BigInteger,
        nullable=False,
        index=True,
    )

    # ✅ إضافة identifier (POSITION_IDENTIFIER) — مهم لحسابات Netting
    identifier = Column(
        BigInteger,
        nullable=True,
        index=True,
    )

    # ✅ إضافة magic للتحقق من ملكية الصفقة
    magic = Column(
        BigInteger,
        nullable=True,
        index=True,
    )

    symbol = Column(String(64), nullable=False, index=True)

    position_type = Column(String(32), nullable=False)

    volume = Column(Numeric, nullable=False)

    open_price = Column(Numeric, nullable=False)

    # ✅ السعر الحالي — nullable لأن الصفقات القديمة قد لا تحتوي عليه
    current_price = Column(
        Numeric,
        nullable=True,
        default=0.0,
    )

    sl = Column(Numeric, nullable=True, default=0.0)
    tp = Column(Numeric, nullable=True, default=0.0)
    profit = Column(Numeric, nullable=False, default=0.0)

    # ✅ وقت فتح الصفقة — nullable للصفقات القديمة
    open_time = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=True,
        server_default=text("NOW()"),
        onupdate=text("NOW()"),
    )

    __table_args__ = (
        # ✅ فهرس مركب لتحسين استعلامات الحساب والرمز
        Index(
            "idx_open_positions_account_symbol",
            "account_number",
            "symbol",
        ),
    )


# ============================================================
# PENDING ORDERS
# ============================================================

class PendingOrder(Base):
    __tablename__ = "pending_orders"

    ticket = Column(BigInteger, primary_key=True)

    account_number = Column(
        BigInteger,
        nullable=False,
        index=True,
    )

    symbol = Column(String, nullable=False, index=True)

    side = Column(String, nullable=False)

    volume = Column(Float, nullable=False)

    price_open = Column(Float, nullable=False)

    stop_loss = Column(Float, nullable=False, default=0.0)
    take_profit = Column(Float, nullable=False, default=0.0)

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=text("NOW()"),
    )


# ============================================================
# BOT STATE
# ============================================================

class BotState(Base):
    __tablename__ = "bot_state"

    id = Column(Integer, primary_key=True, default=1)

    is_running = Column(Boolean, nullable=False, default=False)

    status = Column(String, nullable=False, default="STOPPED")

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=text("NOW()"),
    )


# ============================================================
# POSITION MANAGEMENT COMMANDS (جديد)
# أوامر إدارة الصفقات المفتوحة: تعديل SL/TP، الإغلاق، الإغلاق الجزئي
# ============================================================

class PositionManagementCommand(Base):
    __tablename__ = "position_management_commands"

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

    account_number = Column(
        BigInteger,
        nullable=False,
        index=True,
    )

    ea_id = Column(String, nullable=False, default="", index=True)

    # ✅ هوية الصفقة المستهدفة
    position_ticket = Column(
        BigInteger,
        nullable=False,
        index=True,
    )

    # ✅ identifier للمراكز في Netting (قد تتغير التذكرة بينما يبقى identifier)
    position_identifier = Column(
        BigInteger,
        nullable=True,
        index=True,
    )

    symbol = Column(String(64), nullable=False)

    # MODIFY_SL_TP / CLOSE_POSITION / PARTIAL_CLOSE /
    # MOVE_TO_BREAKEVEN / TRAILING_STOP
    action = Column(String(32), nullable=False)

    # القيم الجديدة (اختيارية حسب نوع الأمر)
    new_sl = Column(Numeric, nullable=True)
    new_tp = Column(Numeric, nullable=True)
    close_volume = Column(Numeric, nullable=True)

    # ✅ سياق القرار للتشخيص
    reason = Column(String(255), nullable=False, default="")
    risk_score = Column(Float, nullable=True)

    # حالة الأمر
    status = Column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
    )

    # ✅ نتيجة التنفيذ من MT5
    mt5_retcode = Column(Integer, nullable=True)
    error_message = Column(String, nullable=True, default="")

    # ✅ القيم المنفذة فعليًا (قد تختلف عن المقترحة بسبب الوسيط)
    executed_sl = Column(Numeric, nullable=True)
    executed_tp = Column(Numeric, nullable=True)

    # ✅ وقت انتهاء صلاحية الأمر
    expires_at = Column(
        DateTime(timezone=True),
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
        onupdate=text("NOW()"),
    )

    __table_args__ = (
        # ✅ فهرس لجلب أمر نشط واحد لكل صفقة
        Index(
            "idx_pm_commands_active_per_position",
            "account_number",
            "position_ticket",
            "status",
        ),

        # ✅ فهرس زمني لسحب الأوامر المعلقة
        Index(
            "idx_pm_commands_pending_created",
            "status",
            "created_at",
        ),
    )


# ============================================================
# POSITION MANAGEMENT STATE (جديد)
# حالة الحماية لكل صفقة مفتوحة
# ============================================================

class PositionManagementState(Base):
    __tablename__ = "position_management_state"

    # ✅ مفتاح مركب: الحساب + تذكرة الصفقة
    # لأن رقم التذكرة لا يُفترض أنه فريد بين جميع الحسابات
    account_number = Column(
        BigInteger,
        primary_key=True,
    )

    position_ticket = Column(
        BigInteger,
        primary_key=True,
    )

    position_identifier = Column(BigInteger, nullable=True, index=True)

    symbol = Column(String(64), nullable=False, index=True)

    # ✅ أعلى ربح عائم مرصود — مطلوب لـ Giveback Protection
    max_floating_profit = Column(
        Numeric,
        nullable=False,
        default=0.0,
    )

    # ✅ أعلى سعر مواتٍ — مطلوب لحساب Trailing دقيق
    max_favorable_price = Column(
        Numeric,
        nullable=True,
    )

    # ✅ المخاطرة الأصلية للصفقة (بالدولار)
    initial_risk = Column(
        Numeric,
        nullable=True,
    )

    # ✅ الوقف الأصلي (قبل أي تعديل)
    initial_sl = Column(
        Numeric,
        nullable=True,
    )

    # ✅ سعر الدخول (يُخزَّن منفصلًا للرجوع إليه)
    entry_price = Column(
        Numeric,
        nullable=True,
    )

    # ✅ أعلام الحماية (مشتقة من SL الفعلي، لكن تُحفظ للرجوع السريع)
    break_even_activated = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    profit_lock_activated = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    trailing_activated = Column(
        Boolean,
        nullable=False,
        default=False,
    )

    # ✅ آخر إجراء إداري تم اتخاذه
    last_management_action = Column(
        String(32),
        nullable=True,
    )

    last_action_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ✅ منع تكرار محاولات الإغلاق
    last_close_attempt = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
        onupdate=text("NOW()"),
    )

    __table_args__ = (
        Index(
            "idx_pm_state_account_ticket",
            "account_number",
            "position_ticket",
        ),
        Index(
            "idx_pm_state_identifier",
            "position_identifier",
        ),
    )
